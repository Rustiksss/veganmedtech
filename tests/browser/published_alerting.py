"""WORK-0020: real HTTPS acceptance on own synthetic fixtures; two generations max.

First run retains private fixture state for the repeat deployment; --resume verifies it
without a generation, then disables only this run's users and relationships.
"""
import argparse,json,secrets,subprocess,time
from pathlib import Path
from bidi import Browser
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/quality/reports/2026-10-26-work-0020'
PRIVATE=Path('/tmp/work0020-private/published-state.json')
SSH=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no','-o','ClearAllForwardings=yes','veganmedtech-server']
BASE='https://94.103.3.149'

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--bidi-port',type=int,default=19288);parser.add_argument('--resume',action='store_true');args=parser.parse_args()
 checks=[];metadata={'accept_insecure_certs':False,'provider':'real Polza','generations':0}
 b=Browser(args.bidi_port,accept_insecure=False)
 def check(name,value):
  checks.append({'name':name,'passed':bool(value)})
  if not value:raise AssertionError(name)
 def op(code):
  r=subprocess.run(SSH+['docker exec -i veganmedtech-app-1 python manage.py shell'],input=code,text=True,capture_output=True,check=True)
  return r.stdout.strip().splitlines()[-1]
 def save():PRIVATE.write_text(json.dumps(state));PRIVATE.chmod(0o600)
 def disable():
  ids=state['ids'];op(f'from accounts.models import User\nfrom care.models import CareRelationship\nCareRelationship.objects.filter(patient_id__in={ids[:2]}).update(active=False)\nUser.objects.filter(pk__in={ids}).update(is_active=False)\nprint("own fixtures disabled; audit and messages retained")\n')
 def route(c,path):
  b.call('browsingContext.activate',{'context':c});b.evaluate(c,'location.hash='+json.dumps(path));time.sleep(.2);b.wait(c,'!loading')
 def fill(c,element,value):
  b.evaluate(c,'(()=>{const x=document.getElementById('+json.dumps(element)+');x.value='+json.dumps(value)+';x.dispatchEvent(new Event("input",{bubbles:true}));return true;})()')
 def login(email):
  c=b.context(private=True);b.viewport(c,1440);b.navigate(c,BASE+'/#/login');b.wait(c,'!loading')
  fill(c,'accountEmail',email);fill(c,'password',state['password']);b.click(c,'#accountForm button[type=submit]');b.wait(c,'!!sessionUser&&!loading&&!authBusy&&readRoute().view!=="login"');return c
 def api(c,path,method='GET',body=None,key=None):
  options={'method':method,'headers':{'Content-Type':'application/json'}}
  if key:options['headers']['Idempotency-Key']=key
  if body is not None:options['body']=json.dumps(body)
  return b.evaluate(c,'(async()=>{const o='+json.dumps(options)+';o.headers["X-CSRFToken"]=document.cookie.split("; ").find(x=>x.startsWith("csrftoken="))?.split("=")[1]||"";const r=await fetch('+json.dumps(path)+',o);return {status:r.status,body:await r.json(),cache:r.headers.get("Cache-Control")};})()')
 state=None;complete=False
 try:
  if args.resume:state=json.loads(PRIVATE.read_text())
  else:
   assert not PRIVATE.exists(),'Existing fixture state must be reviewed or resumed, not replaced'
   suffix='work0020-live-'+secrets.token_hex(5);password=secrets.token_urlsafe(24)
   code='from accounts.tests.helpers import user\nfrom care.models import CareRelationship\nfrom audit.events import record\nimport json\n'
   code+=f'p=user("p-{suffix}@example.test");p2=user("p2-{suffix}@example.test");d=user("d-{suffix}@example.test","doctor",True);d2=user("d2-{suffix}@example.test","doctor",True)\n'
   code+=f'users=[p,p2,d,d2]\n[u.set_password({password!r}) for u in users]\n[u.save() for u in users]\n'
   code+='CareRelationship.objects.create(patient=p,doctor=d)\nCareRelationship.objects.create(patient=p2,doctor=d2)\nrecord(None,"fixture.create",subject="service:work0020")\nprint(json.dumps({"ids":[u.pk for u in users],"emails":[u.email for u in users]}))\n'
   state=json.loads(op(code));state['password']=password;state['turns']=[];state['keys']=[];save()
  pa,pb,doctor,other=[login(email) for email in state['emails']]
  route(pa,'/patient/assistant');route(doctor,'/doctor/assistant-alerts')
  mode=api(pa,'/api/me/assistant/messages')['body'];check('published demo enabled and clinical detection disabled',mode['alerting_mode']=='demo' and not mode['automatic_detection_enabled'])
  check('patient boundary discloses sharing',b.evaluate(pa,'document.querySelector(".assistant-boundary").textContent.includes("ведущему врачу")'))
  if args.resume:
   turns=api(pa,'/api/me/assistant/messages')['body']['results']
   check('same two successful turns after repeat',sorted(x['id'] for x in turns)==sorted(state['turns']) and all(x['status']=='completed' for x in turns))
   event=api(doctor,'/api/doctor/assistant-notifications/'+str(state['event']))
   check('same seen event after repeat',event['status']==200 and bool(event['body']['seen_at']))
   check('old key still replays saved turn',api(pa,'/api/me/assistant/messages','POST',{'text':state['texts'][0]},state['keys'][0])['body']['id']==state['turns'][0])
  else:
   state['texts']=['Это вымышленный пример: я не хочу жить.','Где в сервисе записать наблюдение?'];save()
   for index,text in enumerate(state['texts']):
    key=secrets.token_hex(16);state['keys'].append(key);save()
    b.evaluate(pa,'(()=>{window.liveOriginalFetch=fetch;window.fetch=(p,o)=>{if(p==="/api/me/assistant/messages"&&o?.method==="POST")o.headers["Idempotency-Key"]='+json.dumps(key)+';return liveOriginalFetch(p,o)};return true;})()')
    fill(pa,'assistantText',text);started=time.monotonic();b.evaluate(pa,'document.querySelector("#assistantForm").requestSubmit()');metadata['generations']+=1
    b.wait(pa,'!state.assistant.pending',30);b.evaluate(pa,'window.fetch=liveOriginalFetch')
    turn=b.evaluate(pa,'state.assistant.items.at(-1)');check('real reply '+str(index),turn and turn['status']=='completed' and bool(turn['reply']))
    state['turns'].append(turn['id']);save()
    if index==0:
     check('real positive signal',turn['analysis_status']=='matched' and turn['notification_status']=='available')
     b.wait(doctor,'state.assistantAlerts.items.length===1',25);metadata['delivery_seconds']=round(time.monotonic()-started,3)
     event=b.evaluate(doctor,'state.assistantAlerts.items[0]');state['event']=event['id'];save()
     check('server evidence and version',event['policy_version']=='chat-alert-demo-v1' and all(a['quote'] in text for a in event['analysis']))
     check('initially unread',event['seen_at'] is None)
     b.click(doctor,'[data-alert-seen="'+str(event['id'])+'"]');b.wait(doctor,'!!state.assistantAlerts.items[0].seen_at')
    else:check('neutral creates no signal',turn['analysis_status']=='no_match' and turn['notification_status']=='none')
   event_id=state['event'];turn_id=state['turns'][0]
   check('other patient denied turn',api(pb,f'/api/me/assistant/messages/{turn_id}')['status']==404)
   check('doctor denied general chat',api(doctor,f'/api/me/assistant/messages/{turn_id}')['status']==403)
   check('other doctor denied event',api(other,f'/api/doctor/assistant-notifications/{event_id}')['status']==404)
   check('patient denied alerts',api(pa,'/api/doctor/assistant-notifications')['status']==403)
   check('no store',api(doctor,f'/api/doctor/assistant-notifications/{event_id}')['cache']=='no-store')
   check('CSRF rejected',b.evaluate(pa,'fetch("/api/me/assistant/messages",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:"invalid"})}).then(r=>r.status===403)'))
   replay=api(pa,'/api/me/assistant/messages','POST',{'text':state['texts'][0]},state['keys'][0]);check('replay no duplicate',replay['status']==200 and replay['body']['id']==turn_id)
   check('conflict rejected',api(pa,'/api/me/assistant/messages','POST',{'text':'Конфликт'},state['keys'][0])['status']==409)
   op(f'from care.models import CareRelationship\nCareRelationship.objects.filter(patient_id={state["ids"][0]}).update(active=False)\nprint("revoked own fixture")\n')
   check('no doctor state is current',api(pa,f'/api/me/assistant/messages/{turn_id}')['body']['notification_status']=='no_doctor')
   check('revoked doctor denied',api(doctor,f'/api/doctor/assistant-notifications/{event_id}')['status']==404)
   op(f'from care.models import CareRelationship\nCareRelationship.objects.create(patient_id={state["ids"][0]},doctor_id={state["ids"][3]})\nprint("reassigned own fixture")\n')
   check('new doctor has own unread state',api(other,f'/api/doctor/assistant-notifications/{event_id}')['body']['seen_at'] is None)
   op(f'from care.models import CareRelationship\nCareRelationship.objects.filter(patient_id={state["ids"][0]}).update(active=False)\nCareRelationship.objects.create(patient_id={state["ids"][0]},doctor_id={state["ids"][2]})\nprint("restored own fixture")\n')
   for width in [1440,390]:
    for c,path,label in [(pa,'/patient/assistant','patient'),(doctor,'/doctor/assistant-alerts','doctor')]:
     b.viewport(c,width);route(c,path);check(f'HTTPS layout {label} {width}',b.evaluate(c,'!routeError&&document.documentElement.scrollWidth<=innerWidth+1'))
     b.screenshot(c,OUT/f'https-{label}-{width}.png')
   metadata['usage']=json.loads(op('from assistant.models import AssistantTurn\nimport json\nprint(json.dumps(list(AssistantTurn.objects.filter(pk__in='+repr(state['turns'])+').values("id","usage","analysis_status"))))\n'))
  for c in [pa,pb,doctor,other]:b.evaluate(c,'logout()');b.wait(c,'!sessionUser&&!loading')
  check('all own sessions logged out',True);complete=True
 finally:
  if state and (args.resume or not complete):disable()
  b.close();(OUT/('https-resume.json' if args.resume else 'https-alerting.json')).write_text(json.dumps({'completed':complete,'checks':checks,'metadata':metadata},ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'passed':len(checks),'metadata':metadata},ensure_ascii=False))
if __name__=='__main__':main()
