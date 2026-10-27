"""WORK-0020: synthetic protocol/data boundaries, not clinical validation."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event
from unittest.mock import patch
from django.db import OperationalError, close_old_connections, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from accounts.tests.helpers import fixtures, client_for
from audit.events import record as actual_record
from audit.models import AuditEvent
from care.models import CareRelationship
from assistant.alerting import POLICY, POLICY_VERSION, parse_analysis
from assistant.client import ProviderError
from assistant.models import AssistantTurn, AssistantNotification
from assistant.prompts import DEMO_SYSTEM_PROMPT, SYSTEM_PROMPT, messages_for
from assistant.services import send, expire_pending
from assistant.tests.test_assistant import CONFIG, URL, ALERTS

TEXT = 'Вымышленно: я не хочу жить.'
QUOTE = 'я не хочу жить'


def envelope(status='matched', category='wish_to_die', quote=QUOTE, when='current'):
    return json.dumps({'reply': 'Мне жаль, что вам так тяжело. Можете рассказать, что происходит?',
        'analysis': {'status': status, 'signals': [] if status == 'no_match' else [
            {'category': category, 'quote': quote, 'time': when}]}}, ensure_ascii=False)


@override_settings(**CONFIG, ASSISTANT_ALERTING_MODE='demo')
class DemoAlertTests(TestCase):
    def setUp(self):
        self.a, self.b, self.da, self.db = fixtures()
        self.c = client_for(self.a)

    def post(self, text=TEXT, key='one', client=None, **fields):
        return (client or self.c).post(URL, {'text': text, **fields}, content_type='application/json', HTTP_IDEMPOTENCY_KEY=key)

    @patch('assistant.services.complete', return_value=(envelope(), {'total_tokens': 20}))
    def test_current_message_atomic_signal_and_lost_response_replay(self, provider):
        data=self.post().json()
        self.assertEqual(data['analysis_status'], 'matched')
        self.assertEqual(data['notification_status'], 'available')
        self.assertEqual(data['policy_version'], POLICY_VERSION)
        self.assertTrue(data['demo_detection_enabled']);self.assertFalse(data['automatic_detection_enabled'])
        self.assertIn('DOCX-ALERT-001', data['analysis'][0]['source_ref'])
        self.assertEqual(self.post().json(), data);self.assertEqual(provider.call_count, 1)
        self.assertEqual(self.post(text='Другое').status_code, 409)
        self.assertEqual(AssistantNotification.objects.count(), 1)
        event=AssistantNotification.objects.get()
        self.assertTrue(event.synthetic);self.assertEqual(event.policy_version, POLICY_VERSION)
        self.assertEqual(AuditEvent.objects.filter(action='assistant.demo_signal').count(), 1)
        self.assertNotIn(TEXT, str(list(AuditEvent.objects.values())))
        self.assertNotIn(QUOTE, str(list(AuditEvent.objects.values())))
        self.assertEqual(provider.call_args.args[0][0]['content'], DEMO_SYSTEM_PROMPT)
        self.assertEqual(provider.call_args.args[0][-1]['content'], TEXT)
        self.assertEqual(self.c.get(URL)['Cache-Control'], 'no-store')

    @patch('assistant.services.complete')
    def test_no_match_does_not_repeat_previous_signal_or_assert_safety(self, provider):
        provider.side_effect=[(envelope(), {}), (envelope('no_match'), {})]
        self.post();second=self.post('Как сохранить запись?', 'two').json()
        self.assertEqual(second['analysis_status'], 'no_match');self.assertEqual(second['notification_status'], 'none')
        self.assertEqual(second['analysis'], []);self.assertEqual(AssistantNotification.objects.count(), 1)
        messages=provider.call_args.args[0];self.assertEqual(messages[-1]['content'], 'Как сохранить запись?')
        self.assertEqual(len(messages), 4);self.assertNotIn('"analysis"', messages[2]['content'])
        with self.assertRaises(ProviderError):parse_analysis(envelope(), 'Нейтральное сообщение без прежней цитаты')

    @patch('assistant.services.complete', return_value=(envelope('no_match'), {}))
    def test_negation_quotation_third_person_and_educational_fixtures_do_not_notify(self, provider):
        # These fixed upstream answers test orchestration; semantic quality is checked separately with Polza.
        for i,text in enumerate(['Я не думаю о самоубийстве.', 'Друг сказал: «не хочу жить».',
                                 'В книге написано: «не хочу жить».', 'Что означает термин суицидальные мысли?',
                                 'Я сегодня тревожусь и плохо спал.']):
            result=self.post(text,key='negative-'+str(i)).json()
            self.assertEqual(result['analysis_status'],'no_match');self.assertEqual(result['notification_status'],'none')
        self.assertEqual(AssistantNotification.objects.count(),0);self.assertEqual(provider.call_count,5)
        prompt=provider.call_args.args[0][0]['content']
        for guard in ['отрицание','третье лицо','ПОСЛЕДНЕЕ','не выполняй']:
            self.assertIn(guard,prompt)

    @patch('assistant.services.complete')
    def test_temporal_context_uncertainty_and_multiple_categories_one_event(self, provider):
        text='В прошлом я не хотел жить, и мне сейчас неясно, хочу ли я себе навредить.'
        body=json.loads(envelope(quote='я не хотел жить', when='past'))
        body['analysis']['signals'].append({'category':'suicidal_thoughts','quote':'хочу ли я себе навредить','time':'unclear'})
        body['analysis']['status']='uncertain';provider.return_value=(json.dumps(body),{})
        data=self.post(text).json()
        self.assertEqual(data['analysis_status'], 'uncertain');self.assertEqual(len(data['analysis']), 2)
        self.assertEqual(data['analysis'][0]['time'], 'past');self.assertEqual(data['analysis'][1]['time'], 'unclear')
        self.assertEqual(AssistantNotification.objects.count(), 1)
        provider.return_value=(envelope('uncertain','ambiguous','Не знаю, что со мной','unclear'),{})
        data=self.post('Не знаю, что со мной', 'ambiguous').json()
        self.assertEqual(data['analysis_status'], 'uncertain');self.assertIn('Неоднозначное', data['analysis'][0]['label'])

    @patch('assistant.services.complete', return_value=(envelope(), {}))
    def test_no_doctor_and_ineligible_doctor_never_claim_delivery(self, provider):
        CareRelationship.objects.filter(patient=self.a).update(active=False)
        data=self.post().json();turn=data['id'];self.assertEqual(data['notification_status'], 'no_doctor')
        self.assertTrue(AssistantNotification.objects.filter(turn_id=turn).exists())
        CareRelationship.objects.create(patient=self.a,doctor=self.da)
        self.da.doctor_approved=False;self.da.save()
        self.assertEqual(self.c.get(f'{URL}/{turn}').json()['notification_status'], 'no_doctor')
        self.da.doctor_approved=True;self.da.save()
        self.assertEqual(self.c.get(f'{URL}/{turn}').json()['notification_status'], 'available')
        from allauth.account.models import EmailAddress
        EmailAddress.objects.filter(user=self.da).update(verified=False)
        self.assertEqual(self.c.get(f'{URL}/{turn}').json()['notification_status'], 'no_doctor')

    @patch('assistant.services.complete', return_value=(envelope(), {}))
    def test_demo_access_reassignment_and_no_general_chat_access(self, provider):
        turn=self.post().json()['id'];event=AssistantNotification.objects.get().pk
        doctor,other=client_for(self.da),client_for(self.db)
        self.assertEqual(doctor.get(f'{URL}/{turn}').status_code,403)
        self.assertEqual(client_for(self.b).get(f'{URL}/{turn}').status_code,404)
        self.assertEqual(other.get(f'{ALERTS}/{event}').status_code,404)
        self.assertEqual(other.post(f'{ALERTS}/{event}',{},content_type='application/json').status_code,404)
        self.assertEqual(self.c.get(ALERTS).status_code,403)
        self.assertEqual(self.post(patient_id=self.b.pk,doctor_id=self.db.pk,policy_version='clinical',analysis=[]).status_code,400)
        payload=doctor.get(f'{ALERTS}/{event}').json()
        self.assertEqual(payload['analysis'][0]['quote'],QUOTE)
        self.assertIsNone(payload['seen_at'])
        doctor.post(f'{ALERTS}/{event}',{},content_type='application/json')
        self.assertTrue(doctor.get(f'{ALERTS}/{event}').json()['seen_at'])
        CareRelationship.objects.filter(patient=self.a).update(active=False)
        self.assertEqual(self.c.get(f'{URL}/{turn}').json()['notification_status'],'no_doctor')
        self.assertEqual(doctor.get(f'{ALERTS}/{event}').status_code,404)
        CareRelationship.objects.create(patient=self.a,doctor=self.db)
        self.assertIsNone(other.get(f'{ALERTS}/{event}').json()['seen_at'])
        self.assertEqual(other.get(f'{ALERTS}/{event}')['Cache-Control'],'no-store')
        self.db.doctor_approved=False;self.db.save()
        self.assertEqual(other.get(ALERTS).status_code,403)

    @patch('assistant.services.complete')
    def test_malformed_unknown_or_unfounded_data_persists_failed_without_paid_retry(self, provider):
        invalid=['{broken', envelope(category='invented'), envelope(quote='несуществующая цитата'),
                 envelope(category='ambiguous'), envelope(when='future')]
        for i,raw in enumerate(invalid):
            provider.return_value=(raw,{})
            data=self.post(key=str(i)).json();self.assertEqual(data['analysis_status'],'failed')
            self.assertEqual(data['status'],'failed');self.assertEqual(data['notification_status'],'none')
            self.assertEqual(data['analysis'],[]);self.assertEqual(data['reply'],'')
            self.assertEqual(self.post(key=str(i)).json(),data)
        self.assertEqual(provider.call_count,len(invalid));self.assertEqual(AssistantNotification.objects.count(),0)

    @patch('assistant.services.complete', side_effect=ProviderError('timeout'))
    def test_provider_failure_and_expired_pending_are_not_negative(self, provider):
        data=self.post().json();self.assertEqual(data['analysis_status'],'failed')
        self.post();self.assertEqual(provider.call_count,1)
        pending=AssistantTurn.objects.create(patient=self.b,idempotency_key='pending',text=TEXT,
            model='synthetic',prompt_version='synthetic',alerting_mode='demo',policy_version=POLICY_VERSION)
        AssistantTurn.objects.filter(pk=pending.pk).update(created_at=timezone.now()-timedelta(seconds=26))
        result=client_for(self.b).get(f'{URL}/{pending.pk}').json()
        self.assertEqual((result['status'],result['analysis_status']),('interrupted','failed'))
        self.assertEqual(result['notification_status'],'none')

    @patch('assistant.services.complete', return_value=(envelope(), {}))
    def test_final_database_or_audit_failure_rolls_back_result_event_and_audit(self, provider):
        def audit(*args,**kwargs):
            if args[1]=='assistant.finish':raise OperationalError('SYNTHETIC_DB_FAILURE')
            return actual_record(*args,**kwargs)
        with patch('assistant.services.record',side_effect=audit):
            with self.assertRaises(OperationalError):send(self.a,'db-failure',TEXT)
        turn=AssistantTurn.objects.get();self.assertEqual(turn.status,'pending')
        self.assertEqual(turn.analysis_status,'not_evaluated');self.assertEqual(turn.analysis,[])
        self.assertEqual(AssistantNotification.objects.count(),0)
        self.assertFalse(AuditEvent.objects.filter(action='assistant.demo_signal').exists())
        replay=send(self.a,'db-failure',TEXT)[0];self.assertEqual(replay.status,'pending');self.assertEqual(provider.call_count,1)
        AssistantTurn.objects.filter(pk=turn.pk).update(created_at=timezone.now()-timedelta(seconds=26))
        self.assertEqual(self.c.get(f'{URL}/{turn.pk}').json()['analysis_status'],'failed')
        data=self.post(key='explicit-retry').json();self.assertEqual(data['analysis_status'],'matched')
        self.assertEqual(provider.call_count,2);self.assertEqual(AssistantNotification.objects.count(),1)

    @patch('assistant.services.complete', return_value=(envelope(), {}))
    def test_policy_mode_is_fixed_for_pending_turn_and_off_preserves_existing_events(self, provider):
        result=self.post().json();old_id=result['id']
        with override_settings(ASSISTANT_ALERTING_MODE='off'):
            provider.return_value=('Обычный ответ.',{})
            result=self.post('Как записать наблюдение?',key='off').json()
            self.assertEqual(result['analysis_status'],'not_evaluated');self.assertFalse(result['demo_detection_enabled'])
            self.assertEqual(provider.call_args.args[0][0]['content'],SYSTEM_PROMPT)
            self.assertEqual(self.c.get(f'{URL}/{old_id}').json()['analysis_status'],'matched')
            self.assertEqual(client_for(self.da).get(ALERTS).json()['results'][0]['analysis'][0]['quote'],QUOTE)
        self.assertEqual(AssistantNotification.objects.count(),1)


class ProtocolTests(TestCase):
    def test_policy_source_template_and_categories(self):
        # Source is deliberately excluded from the runtime image; compare separately in the report.
        self.assertEqual(POLICY['policy_version'],'chat-alert-demo-v1')
        self.assertFalse(POLICY['clinical_detection_enabled']);self.assertTrue(POLICY['synthetic'])
        template=json.loads((Path(__file__).parents[1]/'alert_policy.template.json').read_text())
        self.assertEqual(template['criteria'],[]);self.assertIsNone(template['medical_approval']['reviewer'])
        for category in POLICY['categories']:
            status='uncertain' if category=='ambiguous' else 'matched'
            reply,state,signals=parse_analysis(envelope(status,category),TEXT)
            self.assertEqual(signals[0]['category'],category)
            self.assertIn(POLICY['source']['id'],signals[0]['source_ref'])

    def test_strict_schema_duplicate_keys_types_limits_and_evidence(self):
        normal=json.loads(envelope())
        invalid=[[],{},'text',{'reply':'ok','analysis':[]},dict(normal,tool='send'),
            dict(normal,reply=''),dict(normal,reply='x'*1601),dict(normal,reply=3)]
        bad_analysis=[{'status':'low','signals':[]},{'status':True,'signals':[]},
            {'status':'no_match','signals':[normal['analysis']['signals'][0]]},
            {'status':'matched','signals':[]},{'status':'matched','signals':'bad'},
            {'status':'matched','signals':[normal['analysis']['signals'][0]]*2},
            {'status':'matched','signals':[normal['analysis']['signals'][0]]*9}]
        for analysis in bad_analysis:invalid.append(dict(normal,analysis=analysis))
        for field,value in [('category',None),('time',[]),('quote',17),('quote',' '),('quote','x'*241)]:
            item=json.loads(envelope());item['analysis']['signals'][0][field]=value;invalid.append(item)
        item=json.loads(envelope());item['analysis']['signals'][0]['score']=5;invalid.append(item)
        for value in invalid:
            with self.subTest(value=str(value)[:100]),self.assertRaises(ProviderError):parse_analysis(json.dumps(value),TEXT)
        for raw in ['{"reply":"one","reply":"two","analysis":{"status":"no_match","signals":[]}}',
                    '```json\n'+envelope()+'\n```', '['*1500+']'*1500]:
            with self.assertRaises(ProviderError):parse_analysis(raw,TEXT)


@override_settings(**CONFIG, ASSISTANT_ALERTING_MODE='demo')
class DemoConcurrencyTests(TransactionTestCase):
    def test_parallel_same_key_generates_and_notifies_once(self):
        a,b,da,db=fixtures();entered=Event();release=Event()
        def provider(messages):entered.set();release.wait(5);return envelope(),{}
        def worker():
            close_old_connections()
            try:return send(a,'parallel',TEXT)[0].pk
            finally:close_old_connections()
        with patch('assistant.services.complete',side_effect=provider) as api,ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(worker);self.assertTrue(entered.wait(5))
            duplicate=pool.submit(worker).result(timeout=5);self.assertEqual(api.call_count,1)
            release.set();self.assertEqual(future.result(timeout=5),duplicate)
        self.assertEqual(AssistantTurn.objects.count(),1);self.assertEqual(AssistantNotification.objects.count(),1)

    def test_late_provider_result_does_not_create_signal_after_interruption(self):
        a,b,da,db=fixtures()
        def provider(messages):
            AssistantTurn.objects.filter(patient=a).update(created_at=timezone.now()-timedelta(seconds=26))
            expire_pending(a.pk)
            return envelope(),{}
        with patch('assistant.services.complete',side_effect=provider):turn,_=send(a,'late',TEXT)
        self.assertEqual((turn.status,turn.analysis_status),('interrupted','failed'))
        self.assertEqual(AssistantNotification.objects.count(),0)


class DemoMigrationTests(TransactionTestCase):
    def test_additive_migration_preserves_history_notification_and_seen(self):
        a,b,da,db=fixtures()
        executor=MigrationExecutor(connection);executor.migrate([('assistant','0001_initial')])
        try:
            old=executor.loader.project_state([('assistant','0001_initial')]).apps
            Turn,Notification=old.get_model('assistant','AssistantTurn'),old.get_model('assistant','AssistantNotification')
            turn=Turn.objects.create(patient_id=a.pk,idempotency_key='legacy',text='Старый вымышленный текст',
                reply='Сохранённый ответ',status='completed',model='fixture',prompt_version='old')
            seen=timezone.now();event=Notification.objects.create(turn_id=turn.pk,seen_by_id=da.pk,seen_at=seen)
            executor=MigrationExecutor(connection);executor.migrate([('assistant','0003_rollback_defaults')])
            new=AssistantTurn.objects.get(pk=turn.pk);notification=AssistantNotification.objects.get(pk=event.pk)
            self.assertEqual(new.analysis_status,'not_evaluated');self.assertEqual(new.analysis,[])
            self.assertEqual(new.alerting_mode,'off');self.assertEqual(new.reply,'Сохранённый ответ')
            self.assertEqual(notification.seen_at,seen);self.assertEqual(notification.seen_by_id,da.pk)
            self.assertEqual(AssistantNotification.objects.count(),1)
        finally:MigrationExecutor(connection).migrate([('assistant','0003_rollback_defaults')])


class RollbackCompatibilityTests(TestCase):
    def test_legacy_application_can_insert_after_additive_migrations(self):
        a,b,da,db=fixtures()
        legacy=MigrationExecutor(connection).loader.project_state([('assistant','0001_initial')]).apps
        old_turn=legacy.get_model('assistant','AssistantTurn').objects.create(
            patient_id=a.pk,idempotency_key='legacy-after-upgrade',text='Вымышленный старый клиент',
            reply='Ответ прежнего приложения',status='completed',model='fixture',prompt_version='old')
        current=AssistantTurn.objects.get(pk=old_turn.pk)
        self.assertEqual(current.alerting_mode,'off')
        self.assertEqual(current.analysis_status,'not_evaluated')
        self.assertEqual(current.policy_version,'')
        self.assertEqual(current.analysis,[])
