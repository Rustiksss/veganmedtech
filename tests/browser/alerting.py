"""Local WORK-0020 browser acceptance with a fixed upstream fixture, no paid calls."""
import json
import secrets
import subprocess
import time
from pathlib import Path
from bidi import Browser

ROOT=Path(__file__).resolve().parents[2]


def run(args):
    if args.project!='veganmedtech-work0020-test' or not args.compose_override:
        raise SystemExit('Only the separate WORK-0020 test project with an explicit override is permitted')
    dc=['docker','compose','--env-file',args.compose_env_file,'-p',args.project,'-f',str(ROOT/'compose.yaml'),
        '-f',args.compose_override,'--profile','dev']
    checks=[];metadata={'provider':'fixed synthetic fixture; real Polza checked separately','widths':[1440,768,390]}
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    b=Browser(args.bidi_port);password=secrets.token_urlsafe(24);suffix=secrets.token_hex(5)
    def check(name,value):
        checks.append({'name':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def op(code):
        p=subprocess.run(dc+['exec','-T','app','python','manage.py','shell'],input=code,text=True,capture_output=True,cwd=ROOT,check=True)
        return p.stdout.strip().splitlines()[-1]
    def route(c,path):
        b.call('browsingContext.activate',{'context':c});b.evaluate(c,'location.hash='+json.dumps(path));time.sleep(.2);b.wait(c,'!loading')
    def fill(c,id,value):
        b.evaluate(c,'(()=>{const el=document.getElementById('+json.dumps(id)+');el.value='+json.dumps(value)+';el.dispatchEvent(new Event("input",{bubbles:true}));return true;})()')
    def api(c,path,method='GET',body=None,key=None):
        options={'method':method,'headers':{'Content-Type':'application/json'}}
        if key:options['headers']['Idempotency-Key']=key
        if body is not None:options['body']=json.dumps(body)
        return b.evaluate(c,'(async()=>{const o='+json.dumps(options)+';o.headers["X-CSRFToken"]=document.cookie.split("; ").find(x=>x.startsWith("csrftoken="))?.split("=")[1]||"";const r=await fetch('+json.dumps(path)+',o);return {status:r.status,body:await r.json()};})()')
    def send(c,text):
        fill(c,'assistantText',text);b.evaluate(c,'document.querySelector("#assistantForm").requestSubmit()');b.wait(c,'!state.assistant.pending',25)
        return b.evaluate(c,'state.assistant.items.at(-1)')
    def login(email):
        c=b.context(private=True);b.viewport(c,1440);b.navigate(c,'http://localhost:18008/#/login');b.wait(c,'!loading')
        fill(c,'accountEmail',email);fill(c,'password',password);b.click(c,'#accountForm button[type=submit]')
        b.wait(c,'!!sessionUser&&!loading&&!authBusy&&readRoute().view!=="login"');return c
    data=json.loads(op('from accounts.tests.helpers import user\nfrom care.models import CareRelationship\nfrom django.core.cache import cache\nimport json\ncache.clear()\n'
        +f'p=user("demo-p-{suffix}@example.test");p2=user("demo-p2-{suffix}@example.test");d=user("demo-d-{suffix}@example.test","doctor",True);d2=user("demo-d2-{suffix}@example.test","doctor",True)\n'
        +f'users=[p,p2,d,d2]\n[u.set_password({password!r}) for u in users]\n[u.save() for u in users]\n'
        +'CareRelationship.objects.create(patient=p,doctor=d)\nCareRelationship.objects.create(patient=p2,doctor=d2)\n'
        +'print(json.dumps({"ids":[u.pk for u in users],"emails":[u.email for u in users]}))\n'))
    try:
        pa,pb,doctor,other=[login(email) for email in data['emails']]
        route(pa,'/patient/assistant');route(doctor,'/doctor/assistant-alerts')
        check('demo boundary before sending',b.evaluate(pa,'state.assistant.mode==="demo"&&document.querySelector(".assistant-boundary").textContent.includes("Polza AI")&&document.querySelector(".assistant-boundary").textContent.includes("ведущему врачу")'))
        check('empty doctor list no safety claim',b.evaluate(doctor,'state.assistantAlerts.items.length===0&&document.querySelector("#assistantAlerts").textContent.includes("не подтверждает отсутствие риска")'))
        if args.reduced_motion_only:
            check('reduced motion preference',b.evaluate(pa,'matchMedia("(prefers-reduced-motion: reduce)").matches'))
            for width in [1440,768,390]:
                for c in [pa,doctor]:
                    b.viewport(c,width);check(f'reduced layout {c} {width}',b.evaluate(c,'document.documentElement.scrollWidth<=innerWidth+1'))
            return
        # Keep the doctor's cabinet visible while the patient sends from an independent session.
        started=time.monotonic();positive=send(pa,'Вымышленный пример: я не хочу жить.')
        check('demo analysis persisted automatically',positive['analysis_status']=='matched' and positive['notification_status']=='available')
        b.wait(doctor,'state.assistantAlerts.items.length===1',24)
        metadata['delivery_seconds']=round(time.monotonic()-started,3)
        event=b.evaluate(doctor,'state.assistantAlerts.items[0]');turn=positive['id'];event_id=event['id']
        metadata['control_ids']={'turn':turn,'event':event_id}
        check('automatic signal delivered by existing cabinet',b.evaluate(doctor,'document.querySelector("#assistantAlerts").textContent.includes("Демонстрационный сигнал")&&document.querySelector("#assistantAlerts").textContent.includes("DOCX-ALERT-001")'))
        check('signal has source version temporal context',event['policy_version']=='chat-alert-demo-v1' and event['analysis'][0]['time']=='current')
        check('delivery is separate from reading',event['seen_at'] is None)
        check('other doctor denied event',api(other,f'/api/doctor/assistant-notifications/{event_id}')['status']==404)
        check('other patient denied chat',api(pb,f'/api/me/assistant/messages/{turn}')['status']==404)
        check('doctor denied whole chat',api(doctor,f'/api/me/assistant/messages/{turn}')['status']==403)
        check('patient denied alerts',api(pa,'/api/doctor/assistant-notifications')['status']==403)
        check('CSRF rejection',b.evaluate(pa,'fetch("/api/me/assistant/messages",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:"invalid"})}).then(r=>r.status===403)'))
        b.click(doctor,f'[data-alert-seen="{event_id}"]');b.wait(doctor,'!!state.assistantAlerts.items[0].seen_at')
        check('explicit read state persisted',bool(api(doctor,f'/api/doctor/assistant-notifications/{event_id}')['body']['seen_at']))
        route(pa,'/patient');route(pa,'/patient/assistant')
        check('history and server delivery status survive navigation',b.evaluate(pa,'state.assistant.items[0].analysis_status==="matched"&&document.querySelector(".analysis-status").textContent.includes("не подтверждает прочтение")'))
        neutral=send(pa,'Как сохранить запись?')
        check('neutral does not repeat historical signal',neutral['analysis_status']=='no_match' and neutral['notification_status']=='none')
        check('no match does not promise safety',b.evaluate(pa,'document.querySelector(".assistant-chat").textContent.includes("не подтверждает отсутствие риска")'))
        historical=send(pa,'В прошлом я думал о самоубийстве.')
        uncertain=send(pa,'Не понимаю, хочу ли я себе навредить.')
        check('past context retained',historical['analysis'][0]['time']=='past')
        check('uncertainty visible and creates event',uncertain['analysis_status']=='uncertain' and uncertain['notification_status']=='available')
        failed=send(pa,'ТЕСТ_ОТКАЗ')
        check('analysis failure is explicit not no match',failed['analysis_status']=='failed' and failed['notification_status']=='none')
        check('failure has explicit retry',b.evaluate(pa,'!!document.querySelector("[data-assistant-retry]")&&document.querySelector(".assistant-chat").textContent.includes("проверка не выполнена")'))
        # Count total attempts: repeating a saved key after a lost response must not add an upstream attempt.
        saved_key=op(f'from assistant.models import AssistantTurn\nprint(AssistantTurn.objects.get(pk={turn}).idempotency_key)\n')
        before=int(op(f'from assistant.models import AssistantAttempt\nprint(AssistantAttempt.objects.filter(patient_id={data["ids"][0]}).count())\n'))
        replay=api(pa,'/api/me/assistant/messages','POST',{'text':positive['text']},saved_key)
        check('saved key returns saved signal',replay['status']==200 and replay['body']['id']==turn)
        check('replay adds no provider attempt',before==int(op(f'from assistant.models import AssistantAttempt\nprint(AssistantAttempt.objects.filter(patient_id={data["ids"][0]}).count())\n')))
        # The isolated browser fixtures never assess HTML; it is rendered only as text.
        op(f'from assistant.models import AssistantTurn\nAssistantTurn.objects.create(patient_id={data["ids"][0]},idempotency_key="html",text=\'<img src=x onerror="window.demoXss=1">\',reply=\'<script>window.demoXss=1</script>\',status="completed",model="fixture",prompt_version="fixture")\nprint("seeded")\n')
        route(pa,'/patient');route(pa,'/patient/assistant');route(doctor,'/doctor/assistant-alerts')
        check('text and replies are escaped',b.evaluate(pa,'!window.demoXss&&!document.querySelector(".assistant-chat img")&&!document.querySelector(".assistant-chat script")'))
        check('all signal kinds reachable',b.evaluate(doctor,'state.assistantAlerts.items.length===3&&document.querySelector("#assistantAlerts").textContent.includes("Время неясно")&&document.querySelector("#assistantAlerts").textContent.includes("Упоминание прошлого")'))
        for width in [1440,768,390]:
            for c,label in [(pa,'assistant'),(doctor,'alerts')]:
                b.viewport(c,width);check(f'layout {label} {width}',b.evaluate(c,'document.documentElement.scrollWidth<=innerWidth+1&&document.querySelectorAll("#pageTitle").length===1'))
                b.screenshot(c,output.with_name(f'demo-{label}-{width}.png'))
        b.call('browsingContext.activate',{'context':pa});b.evaluate(pa,'document.querySelector("#pageTitle").focus()');reached=False
        for _ in range(45):
            b.call('input.performActions',{'context':pa,'actions':[{'type':'key','id':'keyboard','actions':[{'type':'keyDown','value':'\ue004'},{'type':'keyUp','value':'\ue004'}]}]})
            if b.evaluate(pa,'document.activeElement.id==="assistantText"'):reached=True;break
        check('keyboard reaches patient input',reached)
        route(doctor,'/doctor/assistant-alerts')
        b.evaluate(doctor,'(()=>{window.demoFetch=fetch;window.fetch=(p,o)=>p.startsWith("/api/doctor/assistant-notifications")?Promise.reject(new TypeError("fixture")):demoFetch(p,o);refreshAssistantAlerts();return true;})()')
        b.wait(doctor,'!!state.assistantAlerts.error');check('failed poll clears sensitive content',b.evaluate(doctor,'state.assistantAlerts.items.length===0'))
        b.evaluate(doctor,'(()=>{window.fetch=demoFetch;refreshAssistantAlerts();return true;})()');b.wait(doctor,'state.assistantAlerts.items.length===3')
        check('retry restores notifications',True)
        # Access is checked again on the server, and subsequent poll removes revoked data.
        op(f'from care.models import CareRelationship\nCareRelationship.objects.filter(patient_id={data["ids"][0]}).update(active=False)\nprint("revoked")\n')
        b.evaluate(doctor,'refreshAssistantAlerts()');b.wait(doctor,'state.assistantAlerts.items.length===0')
        check('revoked doctor no longer reads event',api(doctor,f'/api/doctor/assistant-notifications/{event_id}')['status']==404)
        state=api(pa,f'/api/me/assistant/messages/{turn}')['body'];check('patient sees current no doctor state',state['notification_status']=='no_doctor')
        op(f'from care.models import CareRelationship\nCareRelationship.objects.create(patient_id={data["ids"][0]},doctor_id={data["ids"][3]})\nprint("reassigned")\n')
        new=api(other,f'/api/doctor/assistant-notifications/{event_id}')['body']
        check('new doctor sees event with own unread state',new['id']==event_id and new['seen_at'] is None)
        # A late response must not reintroduce old chat after logout.
        b.viewport(pa,1440);route(pa,'/patient/assistant')
        b.evaluate(pa,'(()=>{window.lateFetch=fetch;window.fetch=(p,o)=>p==="/api/me/assistant/messages"&&o?.method==="POST"?new Promise(r=>window.lateDemo=r):lateFetch(p,o);return true;})()')
        fill(pa,'assistantText','Поздний ответ');b.evaluate(pa,'document.querySelector("#assistantForm").requestSubmit()');b.wait(pa,'state.assistant.pending')
        b.click(pa,'[data-action="logout"]');b.wait(pa,'!sessionUser&&!loading')
        b.evaluate(pa,'(()=>{lateDemo(new Response(JSON.stringify({id:999999,text:"PRIVATE_LATE",reply:"PRIVATE_LATE",status:"completed",created_at:new Date().toISOString()}),{status:201,headers:{"Content-Type":"application/json"}}));window.fetch=lateFetch;return true;})()');time.sleep(.2)
        check('logout ignores late signal response',b.evaluate(pa,'state.assistant.items.length===0&&state.assistant.mode==="off"&&!document.body.textContent.includes("PRIVATE_LATE")'))
        metadata['control_snapshot']=json.loads(op(f'from assistant.models import AssistantTurn,AssistantNotification\nimport json\nprint(json.dumps({{"turns":AssistantTurn.objects.filter(patient_id={data["ids"][0]}).count(),"events":AssistantNotification.objects.filter(turn__patient_id={data["ids"][0]}).count()}}))\n'))
    finally:
        op(f'from accounts.models import User\nfrom care.models import CareRelationship\nUser.objects.filter(pk__in={data["ids"]}).update(is_active=False)\nCareRelationship.objects.filter(patient_id__in={data["ids"][:2]}).update(active=False)\nprint("synthetic users disabled; audit retained")\n')
        b.close();output.write_text(json.dumps({'checks':checks,'metadata':metadata},ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'passed':sum(x['passed'] for x in checks),'total':len(checks),'metadata':metadata},ensure_ascii=False))
