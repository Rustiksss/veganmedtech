"""One live post-deployment backend smoke; own fictional accounts, no model benchmark."""
import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from scripts.benchmark_assistant import Budget,upper_cost,append_json,digest
SSH=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no','-o','ClearAllForwardings=yes','-o','ConnectTimeout=10','veganmedtech-server']
TEXT='Мне тяжело, я не хочу жить.'
expected={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['backend/assistant/client.py','backend/assistant/prompts.py','backend/config/settings.py']}
def shell(code):
 r=subprocess.run(SSH+['docker exec -i veganmedtech-app-1 python manage.py shell'],input=code,text=True,capture_output=True,timeout=45,check=True)
 return json.loads(r.stdout.strip().splitlines()[-1])
prepared=shell('from django.conf import settings\nfrom assistant.prompts import messages_for\nfrom types import SimpleNamespace\nfrom pathlib import Path\nimport json,hashlib,http.client,ssl\nassert settings.POLZA_MODEL=="cohere/command-r7b-12-2024"\nexpected='+repr(expected)+'\nassert all(hashlib.sha256((Path("/app")/p).read_bytes()).hexdigest()==h for p,h in expected.items())\nc=http.client.HTTPSConnection("polza.ai",timeout=18,context=ssl.create_default_context());c.request("GET","/api/v1/models/cohere/command-r7b-12-2024");r=c.getresponse();assert r.status==200;data=json.loads(r.read(1048576));c.close()\np=next(p for p in data["providers"] if p["name"]=="cohere");assert float(p["pricing"]["prompt_per_million"])<=4.3 and float(p["pricing"]["completion_per_million"])<=17.2\nprint(json.dumps({"messages":messages_for(SimpleNamespace(text='+repr(TEXT)+',alerting_mode="demo"),[])}))\n')
config={'id':'cohere-deploy-r13','model':'cohere/command-r7b-12-2024','provider':'cohere','input_price':4.3,'output_price':17.2,'request_fee':0,'response_format':{'type':'json_object'}}
upper=upper_cost(config,prepared['messages']);key='work0020-deploy-smoke-rev13';budget=Budget();journal=OUT/'deploy-smoke-rev13.jsonl'
attempt=budget.reserve(key,upper,digest(expected),config,'https',public=True,evidence=str(journal.relative_to(ROOT)))
append_json(journal,{'type':'reservation','attempt':attempt,'attempt_key':key,'upper_cost_rub':upper})
code='''from accounts.tests.helpers import user,client_for
from accounts.models import User
from care.models import CareRelationship
from assistant.models import AssistantTurn
from audit.events import record
from django.conf import settings
import json,secrets,time
assert settings.POLZA_MODEL=='cohere/command-r7b-12-2024'
users=[];result={}
try:
 suffix=secrets.token_hex(6);p=user('deploy-p-'+suffix+'@example.test');users.append(p);d=user('deploy-d-'+suffix+'@example.test','doctor',True);users.append(d)
 for u in users:u.set_unusable_password();u.save(update_fields=['password'])
 CareRelationship.objects.create(patient=p,doctor=d);record(None,'fixture.create',subject='service:work0020-deploy')
 start=time.monotonic();response=client_for(p).post('/api/me/assistant/messages',{'text':__SMOKE_TEXT__},content_type='application/json',HTTP_IDEMPOTENCY_KEY=__SMOKE_KEY__,secure=True,HTTP_HOST='94.103.3.149');elapsed=round(time.monotonic()-start,3)
 body=response.json();result={'http_status':response.status_code,'seconds':elapsed,'status':body.get('status'),'reply':body.get('reply'),'analysis_status':body.get('analysis_status'),'notification_status':body.get('notification_status')}
 turn=AssistantTurn.objects.filter(patient=p,idempotency_key=__SMOKE_KEY__).first();result['usage']=turn.usage if turn else {};result['stored_model']=turn.model if turn else None
 doctor=client_for(d);events=doctor.get('/api/doctor/assistant-notifications',secure=True,HTTP_HOST='94.103.3.149').json()['results'];result['doctor_events']=len(events)
 if events:
  event=events[0];seen=doctor.post('/api/doctor/assistant-notifications/'+str(event['id']),{},content_type='application/json',secure=True,HTTP_HOST='94.103.3.149');result['doctor_seen']=seen.status_code==200 and bool(seen.json().get('seen_at'))
finally:
 CareRelationship.objects.filter(patient_id__in=[u.pk for u in users if u.role=='patient']).update(active=False)
 User.objects.filter(pk__in=[u.pk for u in users]).update(is_active=False)
 result['own_accounts_disabled']=True
print(json.dumps(result,ensure_ascii=False))
'''.replace('__SMOKE_TEXT__',repr(TEXT)).replace('__SMOKE_KEY__',repr(key))
try:
 result=shell(code);passed=result.get('status')=='completed' and bool(result.get('reply'))
 append_json(journal,{'type':'result','attempt':attempt,'attempt_key':key,'upper_cost_rub':upper,**result})
 budget.outcome(key,'completed' if passed else 'failed',True if passed else None)
 (OUT/'deploy-smoke-rev13.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False));assert passed,'Published model response was not completed'
 assert result['usage'].get('cost',0)<=min(.1,upper)
except BaseException:
 with budget.locked() as ledger:pending=next(s for s in ledger['series'] if s.get('attempt_key')==key)['outcome']=='reserved'
 if pending:budget.outcome(key,'unknown')
 raise
