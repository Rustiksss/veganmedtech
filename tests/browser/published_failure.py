"""Inspect/replay the saved failed live turn, without another provider call."""
import json,subprocess,time
from pathlib import Path
from bidi import Browser

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/quality/reports/2026-10-26-work-0020'
state=json.loads(Path('/tmp/work0020-private/published-state.json').read_text())
SSH=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no','-o','ClearAllForwardings=yes','veganmedtech-server']
checks=[]

def op(code):
    result=subprocess.run(SSH+['docker exec -i veganmedtech-app-1 python manage.py shell'],input=code,text=True,capture_output=True,check=True)
    return result.stdout.strip().splitlines()[-1]

def check(name,value):
    checks.append({'name':name,'passed':bool(value)})
    if not value:raise AssertionError(name)

def set_active(active):
    op('from accounts.models import User\nfrom care.models import CareRelationship\n'
       f'users=User.objects.filter(pk__in={state["ids"]},email__contains="work0020-live-")\n'
       'assert users.count()==4\n'
       f'users.update(is_active={active!r})\n'
       f'CareRelationship.objects.filter(patient_id__in={state["ids"][:2]}).update(active={active!r})\nprint("own fixtures updated")\n')

def statistics():
    return json.loads(op('import json\nfrom assistant.models import AssistantTurn,AssistantAttempt,AssistantNotification\n'
        f'ids={state["ids"][:2]}\n'
        'print(json.dumps({"turns":AssistantTurn.objects.filter(patient_id__in=ids).count(),"attempts":AssistantAttempt.objects.filter(patient_id__in=ids).count(),"events":AssistantNotification.objects.filter(turn__patient_id__in=ids).count()}))\n'))

b=Browser(19288,accept_insecure=False)
try:
    set_active(True);before=statistics();contexts=[]
    for email in state['emails'][:3]:
        c=b.context(private=True);contexts.append(c);b.viewport(c,1440);b.navigate(c,'https://94.103.3.149/#/login');b.wait(c,'!loading')
        b.evaluate(c,'(()=>{document.getElementById("accountEmail").value='+json.dumps(email)+';document.getElementById("password").value='+json.dumps(state['password'])+';document.querySelector("#accountForm").requestSubmit();return true;})()')
        b.wait(c,'!!sessionUser&&!loading&&!authBusy&&readRoute().view!=="login"')
    patient,other,doctor=contexts
    def route(c,path):
        b.call('browsingContext.activate',{'context':c});b.evaluate(c,'location.hash='+json.dumps(path));time.sleep(.2);b.wait(c,'!loading')
    def api(c,path,method='GET',body=None,key=None):
        options={'method':method,'headers':{'Content-Type':'application/json'}}
        if body is not None:options['body']=json.dumps(body)
        if key:options['headers']['Idempotency-Key']=key
        return b.evaluate(c,'(async()=>{const o='+json.dumps(options)+';o.headers["X-CSRFToken"]=document.cookie.split("; ").find(x=>x.startsWith("csrftoken="))?.split("=")[1]||"";const r=await fetch('+json.dumps(path)+',o);return {status:r.status,body:await r.json(),cache:r.headers.get("Cache-Control")};})()')
    route(patient,'/patient/assistant');route(doctor,'/doctor/assistant-alerts')
    history=api(patient,'/api/me/assistant/messages')['body'];turn=history['results'][0]
    check('one saved failed live turn',len(history['results'])==1 and turn['status']=='failed' and turn['analysis_status']=='failed' and not turn['reply'])
    check('demo enabled clinical disabled',history['alerting_mode']=='demo' and not history['automatic_detection_enabled'])
    check('no false event or delivery',turn['notification_status']=='none' and before['events']==0 and api(doctor,'/api/doctor/assistant-notifications')['body']['results']==[])
    check('failure is explicit in UI',b.evaluate(patient,'document.querySelector(".analysis-status").textContent.includes("проверка не выполнена")'))
    check('foreign patient denied',api(other,f'/api/me/assistant/messages/{turn["id"]}')['status']==404)
    check('doctor denied chat',api(doctor,f'/api/me/assistant/messages/{turn["id"]}')['status']==403)
    check('patient denied doctor events',api(patient,'/api/doctor/assistant-notifications')['status']==403)
    check('history no-store',api(patient,'/api/me/assistant/messages')['cache']=='no-store')
    replay=api(patient,'/api/me/assistant/messages','POST',{'text':turn['text']},state['keys'][0])
    check('same failed turn replayed without a new request',replay['status']==200 and replay['body']['id']==turn['id'] and replay['body']['analysis_status']=='failed')
    check('key conflict rejected',api(patient,'/api/me/assistant/messages','POST',{'text':'Конфликт'},state['keys'][0])['status']==409)
    check('CSRF required',b.evaluate(patient,'fetch("/api/me/assistant/messages",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:"invalid"})}).then(r=>r.status===403)'))
    for width in [1440,390]:
        for c,path,label in [(patient,'/patient/assistant','patient'),(doctor,'/doctor/assistant-alerts','doctor')]:
            b.viewport(c,width);route(c,path);check(f'failed state layout {label} {width}',b.evaluate(c,'!routeError&&document.documentElement.scrollWidth<=innerWidth+1'))
            b.screenshot(c,OUT/f'https-failure-{label}-{width}.png')
    b.navigate(patient,'https://94.103.3.149/#/patient/assistant');b.wait(patient,'!loading')
    check('failure persists after reload and repeat deploy',b.evaluate(patient,'state.assistant.items.length===1&&state.assistant.items[0].analysis_status==="failed"'))
    for c in contexts:b.evaluate(c,'logout()');b.wait(c,'!sessionUser&&!loading')
    check('logout clears history',b.evaluate(patient,'state.assistant.items.length===0'))
    check('no new provider attempts turns or events',before==statistics())
finally:
    b.close();set_active(False)
    (OUT/'https-failure.json').write_text(json.dumps({'accept_insecure_certs':False,'new_generations':0,'checks':checks},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'passed':len(checks),'new_generations':0}))
