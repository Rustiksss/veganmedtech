"""WORK-0016: isolated Firefox + real API, only synthetic data. No key is read here."""
import argparse
import json
import re
import secrets
import subprocess
import time
import urllib.request
from pathlib import Path
from bidi import Browser

ROOT = Path(__file__).resolve().parents[2]


def internet_check(args):
    """WORK-0017: approved synthetic acceptance of the deployed assistant, valid TLS."""
    base='https://94.103.3.149'
    private=Path('/tmp/work0017-private')
    output=ROOT/'docs/quality/reports/2026-10-26-work-0017'
    ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no',
         '-o','ClearAllForwardings=yes','veganmedtech-server']
    checks=[];metadata={};emails=[];password=secrets.token_urlsafe(24)
    suffix='work0017-'+secrets.token_hex(5)
    b=Browser(args.bidi_port,accept_insecure=False)

    def check(name,value):
        checks.append({'name':name,'passed':bool(value)})
        if not value:raise AssertionError(name)

    def op(code):
        p=subprocess.run(ssh+['docker exec -i veganmedtech-app-1 python manage.py shell'],
            input=code,text=True,capture_output=True,check=True)
        return p.stdout.strip().splitlines()[-1]

    def operator(*command):
        subprocess.run(ssh+['docker','exec','-i','veganmedtech-app-1','python','manage.py',*command],
            check=True,stdout=subprocess.DEVNULL)

    def route(c,path):
        b.call('browsingContext.activate',{'context':c})
        b.evaluate(c,'location.hash='+json.dumps(path));time.sleep(.25);b.wait(c,'!loading')

    def fill(c,values):
        b.evaluate(c,'(()=>{for(const [id,value] of Object.entries('+json.dumps(values)+')){const el=document.getElementById(id);el.value=value;el.dispatchEvent(new Event("input",{bubbles:true}));}return true;})()')

    def submit(c,selector='#accountForm button[type=submit]'):
        b.click(c,selector)

    def api(c,path):
        return b.evaluate(c,'(async()=>{const r=await fetch('+json.dumps(path)+');return {status:r.status,body:await r.json()};})()')

    def create(role,label):
        email=label+'-'+suffix+'@example.test';emails.append(email)
        c=b.context(private=True);b.viewport(c,1440);b.navigate(c,base+'/#/register/'+role);b.wait(c,'!loading')
        fill(c,{'profileName':'Вымышленный '+label,'accountEmail':email,'password':password,'password_repeat':password});submit(c);b.wait(c,'!authBusy')
        check(label+' registration',bool(b.evaluate(c,'authNotice')) and not b.evaluate(c,'authError'))
        code='''import json,re,time,urllib.request
email=EMAIL
for attempt in range(40):
 with urllib.request.urlopen('http://127.0.0.1:18025/api/v1/messages?limit=1000') as r:messages=json.load(r)['messages']
 for msg in messages:
  if any(x.get('Address')==email for x in msg.get('To',[])):
   with urllib.request.urlopen('http://127.0.0.1:18025/api/v1/message/'+msg['ID']) as r:body=json.load(r)
   match=re.search(r'https?://[^\\s<>]+/#/verify-email/[^\\s<>]+',body.get('Text',''))
   if match:print(match.group(0));raise SystemExit(0)
 time.sleep(.25)
raise SystemExit('Synthetic confirmation missing')
'''.replace('EMAIL',repr(email))
        url=subprocess.check_output(ssh+['python3 -'],input=code.encode()).decode().strip()
        check(label+' HTTPS confirmation',url.startswith(base+'/#/verify-email/'))
        b.navigate(c,url);b.wait(c,'!loading');submit(c);b.wait(c,'!authBusy')
        route(c,'/login');fill(c,{'accountEmail':email,'password':password});submit(c)
        b.wait(c,'!!sessionUser&&!loading&&!authBusy&&readRoute().view!=="login"')
        check(label+' real login',b.evaluate(c,'sessionUser.role')==role)
        return c,email,b.evaluate(c,'sessionUser.id')

    try:
        pa,pe,pid=create('patient','patient-a');pb,pbe,pbid=create('patient','patient-b')
        da,de,did=create('doctor','doctor-a');db,dbe,dbid=create('doctor','doctor-b')
        for email in [de,dbe]:operator('doctor_access','approve',email)
        operator('care_relationship','assign',pe,de);operator('care_relationship','assign',pbe,dbe)
        route(pa,'/patient/assistant')
        check('assistant visible with disabled detection',b.evaluate(pa,'!!document.querySelector("#assistantForm")&&document.querySelector(".assistant-boundary").textContent.includes("отключены")'))
        latencies=[]
        for text in ['Как добавить вымышленное наблюдение о самочувствии в сервисе?','А где потом найти эту запись?']:
            fill(pa,{'assistantText':text});started=time.monotonic();submit(pa,'#assistantForm button[type=submit]')
            b.wait(pa,'!state.assistant.pending',30)
            check('real Polza answer '+str(len(latencies)+1),b.evaluate(pa,'!state.assistant.error&&state.assistant.items.every(m=>m.status==="completed"&&m.reply.length>0)'))
            latencies.append(round(time.monotonic()-started,3))
        check('context points to history',b.evaluate(pa,'state.assistant.items.at(-1).reply.toLowerCase().includes("истори")'))
        turns=b.evaluate(pa,'state.assistant.items.map(m=>m.id)');metadata['latencies_seconds']=latencies
        b.navigate(pa,base+'/#/patient/assistant');b.wait(pa,'!loading')
        check('chat survives reload',b.evaluate(pa,'state.assistant.items.length===2'))
        check('other patient cannot read chat',api(pb,f'/api/me/assistant/messages/{turns[0]}')['status']==404)
        route(da,'/doctor/assistant-alerts');route(db,'/doctor/assistant-alerts')
        check('doctor cannot read private chat',api(da,f'/api/me/assistant/messages/{turns[0]}')['status']==403)
        check('patient cannot read doctor alerts',api(pa,'/api/doctor/assistant-notifications')['status']==403)
        check('automatic detector off',api(pa,'/api/me/assistant/messages')['body']['automatic_detection_enabled'] is False)
        check('no automatic event',int(op(f'from assistant.models import AssistantNotification\nprint(AssistantNotification.objects.filter(turn__patient_id={pid}).count())\n'))==0)
        route(pa,'/patient/report');fill(pa,{'reportText':'Вымышленная контрольная запись WORK-0017'});submit(pa,'#reportForm button[type=submit]')
        b.wait(pa,'!loading&&readRoute().view==="history"')
        report_id=b.evaluate(pa,'state.reports[0].id')
        route(da,'/doctor/assistant-alerts');check('doctor alert list initially empty',b.evaluate(da,'state.assistantAlerts.items.length===0'))
        started=time.monotonic()
        event=int(op(f'from assistant.services import create_synthetic_notification\nprint(create_synthetic_notification({turns[0]}).pk)\n'))
        b.wait(da,'state.assistantAlerts.items.length===1',25)
        metadata['notification_seconds']=round(time.monotonic()-started,3)
        check('synthetic event delivered to leading doctor',b.evaluate(da,'document.querySelector("#assistantAlerts").textContent.includes("Синтетическое событие")'))
        check('foreign doctor denied event',api(db,f'/api/doctor/assistant-notifications/{event}')['status']==404)
        submit(da,f'[data-alert-seen="{event}"]');b.wait(da,'!!state.assistantAlerts.items[0].seen_at')
        check('seen is explicitly recorded',True)
        for width in [1440,390]:
            for c,path,label in [(pa,'/patient/assistant','assistant'),(da,'/doctor/assistant-alerts','alerts')]:
                b.viewport(c,width);route(c,path)
                check(label+' layout '+str(width),b.evaluate(c,'document.documentElement.scrollWidth<=innerWidth+1&&!!document.querySelector("#pageTitle")'))
                b.screenshot(c,output/f'{label}-{width}.png')
        check('CSRF rejected over HTTPS',b.evaluate(pa,'fetch("/api/me/assistant/messages",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:"invalid"})}).then(r=>r.status===403)'))
        cookies=b.call('storage.getCookies',{'partition':{'type':'context','context':pa}})['cookies']
        cookie=next(x for x in cookies if x['name']=='sessionid')
        check('Secure HttpOnly session',cookie['secure'] and cookie['httpOnly'])
        metadata['usage']=json.loads(op('from assistant.models import AssistantTurn\nimport json\nprint(json.dumps(list(AssistantTurn.objects.filter(pk__in='+repr(turns)+').values("id","model","usage"))))\n'))
        state={'patient':pid,'other_patient':pbid,'doctor':did,'other_doctor':dbid,'emails':emails,
            'password':password,'turns':turns,'event':event,'report':report_id}
        p=private/'acceptance-state.json';p.write_text(json.dumps(state));p.chmod(0o600)
        for c in [pa,pb,da,db]:
            b.evaluate(c,'logout()');b.wait(c,'!sessionUser&&!loading')
        check('all synthetic sessions logged out',True)
        metadata['control_ids']={k:state[k] for k in ['patient','turns','event','report']}
    except Exception:
        # Failed runs retain audit but must not leave accessible synthetic accounts.
        op('from accounts.models import User\nfrom care.models import CareRelationship\nusers=User.objects.filter(email__in='+repr(emails)+')\nCareRelationship.objects.filter(patient__in=users).update(active=False)\nusers.update(is_active=False)\nprint("disabled")\n')
        raise
    finally:
        b.close()
        (output/'internet-assistant.json').write_text(json.dumps({'checks':checks,'metadata':metadata,'accept_insecure_certs':False},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':len(checks),'metadata':metadata},ensure_ascii=False))


def internet_resume(args):
    """Verify saved own records after the repeat; deactivate this run's fixtures."""
    state=json.loads(Path('/tmp/work0017-private/acceptance-state.json').read_text())
    base='https://94.103.3.149';checks=[]
    b=Browser(args.bidi_port,accept_insecure=False)
    ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','veganmedtech-server']
    def check(name,value):
        checks.append({'name':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def login(email):
        c=b.context(private=True);b.viewport(c,1440);b.navigate(c,base+'/#/login');b.wait(c,'!loading')
        b.evaluate(c,'(()=>{for(const [id,value] of Object.entries('+json.dumps({'accountEmail':email,'password':state['password']})+')){document.getElementById(id).value=value;}return true;})()')
        b.click(c,'#accountForm button[type=submit]');b.wait(c,'!!sessionUser&&!loading&&!authBusy&&readRoute().view!=="login"')
        return c
    def route(c,path):
        b.call('browsingContext.activate',{'context':c});b.evaluate(c,'location.hash='+json.dumps(path));time.sleep(.25);b.wait(c,'!loading')
    try:
        pa=login(state['emails'][0]);route(pa,'/patient/assistant')
        check('saved two replies after repeat',b.evaluate(pa,'state.assistant.items.length===2&&state.assistant.items.every(m=>m.status==="completed"&&m.reply.length>0)'))
        check('same turn ids after repeat',b.evaluate(pa,'state.assistant.items.map(m=>m.id).sort((a,b)=>a-b)')==sorted(state['turns']))
        route(pa,'/patient/history')
        check('same self report after repeat',b.evaluate(pa,'state.reports.some(r=>r.id==='+str(state['report'])+')'))
        doctor=login(state['emails'][2]);route(doctor,'/doctor/assistant-alerts')
        b.wait(doctor,'state.assistantAlerts.items.length===1')
        check('same notification and seen after repeat',b.evaluate(doctor,'state.assistantAlerts.items[0].id==='+str(state['event'])+'&&!!state.assistantAlerts.items[0].seen_at'))
        for c in [pa,doctor]:b.evaluate(c,'logout()');b.wait(c,'!sessionUser&&!loading')
        check('repeat sessions logged out',True)
    finally:
        assert all(email.endswith('@example.test') and '-work0017-' in email for email in state['emails'])
        for email in state['emails'][:2]:
            subprocess.run(ssh+['docker','exec','veganmedtech-app-1','python','manage.py','care_relationship','revoke',email],check=True,stdout=subprocess.DEVNULL)
        code='from accounts.models import User\nusers=User.objects.filter(email__in='+repr(state['emails'])+')\nusers.update(is_active=False)\nprint(users.filter(is_active=True).count())\n'
        p=subprocess.run(ssh+['docker exec -i veganmedtech-app-1 python manage.py shell'],input=code,text=True,capture_output=True,check=True)
        check('own accounts disabled',p.stdout.strip().splitlines()[-1]=='0')
        b.close()
        (ROOT/'docs/quality/reports/2026-10-26-work-0017/internet-after-repeat.json').write_text(json.dumps({'checks':checks,'accept_insecure_certs':False},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':len(checks),'synthetic_accounts_disabled':True}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compose-env-file')
    parser.add_argument('--compose-override')
    parser.add_argument('--project', default='veganmedtech-work0008-test')
    parser.add_argument('--demo-alerting', action='store_true')
    parser.add_argument('--provider-fixture', action='store_true')
    parser.add_argument('--internet-check',action='store_true')
    parser.add_argument('--internet-resume',action='store_true')
    parser.add_argument('--reduced-motion-only',action='store_true')
    parser.add_argument('--bidi-port', type=int, default=19228)
    parser.add_argument('--output', default=str(ROOT/'docs/quality/reports/2026-10-25-work-0016/browser-assistant.json'))
    args = parser.parse_args()
    if args.internet_resume:
        return internet_resume(args)
    if args.internet_check:
        return internet_check(args)
    if not args.compose_env_file:
        parser.error('--compose-env-file is required for local acceptance')
    if args.demo_alerting:
        from alerting import run
        return run(args)
    if args.project not in {'veganmedtech-work0008-test','veganmedtech-work0020-test'}:
        parser.error('Only an explicitly named synthetic project is permitted')
    private = Path('/tmp/work0016-private')
    dc = ['docker','compose','--env-file',args.compose_env_file,'-p',args.project,
          '-f',str(ROOT/'compose.yaml'),'-f',args.compose_override or str(private/'compose.test.yaml'),'--profile','dev']
    base='http://localhost:18008'
    results=[]; metadata={'provider':'fixed synthetic fixture' if args.provider_fixture else 'real Polza'}

    def check(name, value):
        results.append({'name':name,'passed':bool(value)})
        if not value:
            raise AssertionError(name)

    def op(code):
        proc=subprocess.run(dc+['exec','-T','app','python','manage.py','shell'],input=code,
            cwd=ROOT,text=True,capture_output=True,check=True)
        return proc.stdout.strip().splitlines()[-1]

    suffix=secrets.token_hex(5);password=secrets.token_urlsafe(24)
    data=json.loads(op("from accounts.tests.helpers import user\nfrom care.models import CareRelationship\nimport json\n"
        +f"p=user('assistant-p-{suffix}@example.test');d=user('assistant-d-{suffix}@example.test','doctor',True);o=user('assistant-o-{suffix}@example.test','doctor',True)\n"
        +f"[u.set_password({password!r}) for u in [p,d,o]]\n[u.save() for u in [p,d,o]]\n"
        +"CareRelationship.objects.create(patient=p,doctor=d)\n"
        +"print(json.dumps({'patient':p.pk,'doctor':d.pk,'other':o.pk,'p_email':p.email,'d_email':d.email,'o_email':o.email}))\n"))
    b=Browser(args.bidi_port)
    contexts=[]

    def route(c,path):
        b.call('browsingContext.activate',{'context':c})
        b.evaluate(c,'location.hash='+json.dumps(path));time.sleep(.2);b.wait(c,'!loading')

    def script(c,code):
        return b.evaluate(c,"(()=>{"+code+";return true;})()")

    def fill(c,element,value):
        b.evaluate(c,f"(()=>{{const x=document.getElementById({json.dumps(element)});x.value={json.dumps(value)};x.dispatchEvent(new Event('input',{{bubbles:true}}));return true;}})()")

    def api(c,path,method='GET',body=None):
        return b.evaluate(c,"(async()=>{const r=await fetch("+json.dumps(path)+",{method:"+json.dumps(method)+",headers:{'Content-Type':'application/json','X-CSRFToken':document.cookie.split('; ').find(x=>x.startsWith('csrftoken='))?.split('=')[1]||''},"+("body:JSON.stringify("+json.dumps(body)+")," if body is not None else '')+"});return {status:r.status,body:await r.json()};})()")

    def login(email):
        c=b.context(private=True);contexts.append(c);b.viewport(c,1440);b.navigate(c,base+'/#/login');b.wait(c,'!loading')
        fill(c,'accountEmail',email);fill(c,'password',password);b.click(c,'#accountForm button[type=submit]')
        b.wait(c,'!!sessionUser&&!loading&&!authBusy&&readRoute().view!=="login"')
        return c

    try:
        pa=login(data['p_email']);doctor=login(data['d_email']);other=login(data['o_email'])
        route(pa,'/patient/assistant')
        check('real chat empty',b.evaluate(pa,'state.assistant.items.length===0&&!!document.querySelector("#assistantForm")'))
        check('external processing and disabled detector visible',b.evaluate(pa,'document.querySelector(".assistant-boundary").textContent.includes("Polza AI")&&document.querySelector(".assistant-boundary").textContent.includes("отключены")'))
        check('one page title',b.evaluate(pa,'document.querySelectorAll("#pageTitle").length===1'))
        if args.reduced_motion_only:
            check('OS reduced motion preference',b.evaluate(pa,'matchMedia("(prefers-reduced-motion: reduce)").matches'))
            check('screen and spinner motion disabled',b.evaluate(pa,'(()=>{const el=document.createElement("span");el.className="spinner screen-enter";document.body.append(el);const ok=getComputedStyle(el).animationName==="none";el.remove();return ok;})()'))
            for width in [1440,768,390]:
                b.viewport(pa,width);check('reduced chat layout '+str(width),b.evaluate(pa,'document.documentElement.scrollWidth<=innerWidth&&!!document.querySelector("label[for=assistantText]")'))
            route(doctor,'/doctor/assistant-alerts');check('reduced notification empty state',b.evaluate(doctor,'!!document.querySelector("#assistantAlerts")'))
            print(json.dumps({'passed':len(results),'reduced_motion':True}));return
        for value in ['   ','x'*2001]:
            fill(pa,'assistantText',value);b.click(pa,'#assistantForm button[type=submit]')
            check('invalid input '+str(len(value)),b.evaluate(pa,'!!state.assistant.error&&!state.assistant.pending&&state.assistant.items.length===0'))
        script(pa,"window.observedFetch=window.fetch;window.fetch=async(path,options)=>{if(path==='/api/me/assistant/messages'&&options?.method==='POST')window.lastAssistantKey=options.headers['Idempotency-Key'];return window.observedFetch(path,options)}")
        text='Как сохранить вымышленное наблюдение в сервисе?'
        fill(pa,'assistantText',text);b.click(pa,'#assistantForm button[type=submit]')
        check('waiting state',b.evaluate(pa,'state.assistant.pending&&document.querySelector("#assistantForm").getAttribute("aria-busy")==="true"'))
        b.wait(pa,'!state.assistant.pending',25)
        check('real browser model reply',b.evaluate(pa,'state.assistant.items[0]?.status==="completed"&&state.assistant.items[0].reply.includes("запис")'))
        turn=b.evaluate(pa,'state.assistant.items[0].id');key=b.evaluate(pa,'window.lastAssistantKey')
        metadata['real_turn_id']=turn
        check('no automatic alert',int(op(f'from assistant.models import AssistantNotification\nprint(AssistantNotification.objects.filter(turn__patient_id={data["patient"]}).count())\n'))==0)
        b.navigate(pa,base+'/#/patient/assistant');b.wait(pa,'!loading')
        check('reload preserves history',b.evaluate(pa,f'state.assistant.items.some(x=>x.id==={turn}&&x.status==="completed")'))
        check('other doctor cannot read chat',api(other,f'/api/me/assistant/messages/{turn}')['status']==403)
        check('patient cannot read alerts',api(pa,'/api/doctor/assistant-notifications')['status']==403)

        # A lost response to an already saved key is checked without another paid model call.
        script(pa,"window.realAssistantFetch=window.fetch;window.fetch=async(path,options)=>{const r=await window.realAssistantFetch(path,options);if(path==='/api/me/assistant/messages'&&options?.method==='POST')throw new TypeError('synthetic network loss');return r}")
        script(pa,'state.assistant.draft='+json.dumps(text)+';state.assistant.sentText='+json.dumps(text)+';state.assistant.key='+json.dumps(key)+';sendAssistant()')
        b.wait(pa,'!state.assistant.pending');check('network loss retains draft/key',b.evaluate(pa,'!!state.assistant.error&&!!state.assistant.key&&!!state.assistant.draft'))
        script(pa,'window.fetch=window.realAssistantFetch;sendAssistant()');b.wait(pa,'!state.assistant.pending')
        metadata['retry_state']=b.evaluate(pa,'({items:state.assistant.items.map(x=>({id:x.id,status:x.status})),error:state.assistant.error,draft:state.assistant.draft,key:state.assistant.key})')
        metadata['first_key_present']=bool(key)
        check('retry gets saved reply without duplicate',b.evaluate(pa,'state.assistant.items.length===1&&!state.assistant.error&&!state.assistant.draft'))

        # Seed only synthetic text; no extra provider calls for rendering/pagination tests.
        op('from assistant.models import AssistantTurn\n'
           +f'AssistantTurn.objects.bulk_create([AssistantTurn(patient_id={data["patient"]},idempotency_key="layout-"+str(i),text="Синтетический текст "+str(i),reply="Учебный ответ",status="completed",model="synthetic",prompt_version="fixture") for i in range(32)])\n'
           +f'AssistantTurn.objects.create(patient_id={data["patient"]},idempotency_key="html",text=\'<img src=x onerror="window.assistantXss=1">\',reply=\'<script>window.assistantXss=2</script>\',status="completed",model="synthetic",prompt_version="fixture")\nprint("seeded")\n')
        route(pa,'/patient');route(pa,'/patient/assistant')
        check('history bounded and has older page',b.evaluate(pa,'state.assistant.items.length===30&&!!state.assistant.cursor'))
        b.click(pa,'[data-assistant-more]');b.wait(pa,'state.assistant.items.length>30')
        check('older page loaded',b.evaluate(pa,'state.assistant.items.length===34&&!state.assistant.cursor'))
        check('untrusted text rendered safely',b.evaluate(pa,'!window.assistantXss&&!document.querySelector(".assistant-chat img")&&!document.querySelector(".assistant-chat script")'))
        for width in [1440,768,390]:
            b.viewport(pa,width);check('patient width '+str(width),b.evaluate(pa,'document.documentElement.scrollWidth<=innerWidth'))
            b.screenshot(pa,Path(args.output).parent/f'assistant-{width}.png')
        b.call('browsingContext.activate',{'context':pa})
        b.evaluate(pa,'document.querySelector("#pageTitle").focus()')
        reached=False
        for _ in range(35):
            b.call('input.performActions',{'context':pa,'actions':[{'type':'key','id':'keyboard','actions':[{'type':'keyDown','value':'\ue004'},{'type':'keyUp','value':'\ue004'}]}]})
            if b.evaluate(pa,'document.activeElement.id==="assistantText"'):reached=True;break
        metadata['keyboard_final_focus']=b.evaluate(pa,'({id:document.activeElement.id,tag:document.activeElement.tagName,hidden:document.hidden})')
        check('keyboard reaches message input',reached)

        route(doctor,'/doctor/assistant-alerts');check('doctor empty notifications',b.evaluate(doctor,'state.assistantAlerts.items.length===0'))
        started=time.monotonic()
        event=int(op(f'from assistant.services import create_synthetic_notification\nprint(create_synthetic_notification({turn}).pk)\n'))
        b.wait(doctor,'state.assistantAlerts.items.length===1',22)
        metadata['delivery_seconds']=round(time.monotonic()-started,3)
        check('poll delivers persisted demo event',b.evaluate(doctor,'document.querySelector("#assistantAlerts").textContent.includes("Синтетическое событие")'))
        check('other doctor sees no notifications',api(other,'/api/doctor/assistant-notifications')['body']['results']==[])
        check('other doctor denied event',api(other,f'/api/doctor/assistant-notifications/{event}')['status']==404)
        b.click(doctor,f'[data-alert-seen="{event}"]');b.wait(doctor,'!!state.assistantAlerts.items[0].seen_at')
        check('explicit seen persisted',bool(api(doctor,f'/api/doctor/assistant-notifications/{event}')['body']['seen_at']))
        check('repeat notification has one id',int(op(f'from assistant.services import create_synthetic_notification\nprint(create_synthetic_notification({turn}).pk)\n'))==event)
        for width in [1440,768,390]:
            b.viewport(doctor,width);check('doctor width '+str(width),b.evaluate(doctor,'document.documentElement.scrollWidth<=innerWidth'))
            b.screenshot(doctor,Path(args.output).parent/f'alerts-{width}.png')
        script(doctor,"window.alertFetch=window.fetch;window.fetch=(path,options)=>path.startsWith('/api/doctor/assistant-notifications')?Promise.reject(new TypeError('synthetic')):window.alertFetch(path,options);refreshAssistantAlerts()")
        b.wait(doctor,'!!state.assistantAlerts.error')
        check('notification transport failure clears stale data',b.evaluate(doctor,'state.assistantAlerts.items.length===0'))
        script(doctor,'window.fetch=window.alertFetch;refreshAssistantAlerts()');b.wait(doctor,'state.assistantAlerts.items.length===1')
        check('notification retry restores data',True)

        # Real app recreate, retaining the new test volume; no existing volumes are removed.
        proc=subprocess.run(dc+['up','-d','--force-recreate','--wait','app'],cwd=ROOT,capture_output=True,text=True)
        check('app recreate succeeds',proc.returncode==0)
        check('off mode survives app recreate',api(pa,'/api/me/assistant/messages')['body']['alerting_mode']=='off')
        check('history survives app recreate',any(x['id']==turn for x in api(pa,'/api/me/assistant/messages?limit=100')['body']['results']))
        check('notification survives app recreate',api(doctor,f'/api/doctor/assistant-notifications/{event}')['status']==200)
        subprocess.run(dc+['stop','db'],cwd=ROOT,check=True,capture_output=True)
        check('database outage is not successful delivery',api(doctor,'/api/doctor/assistant-notifications')['status']>=500)
        subprocess.run(dc+['up','-d','--wait','db'],cwd=ROOT,check=True,capture_output=True)
        check('event retained after DB recovery',api(doctor,f'/api/doctor/assistant-notifications/{event}')['status']==200)
        op(f'from care.models import CareRelationship\nCareRelationship.objects.filter(patient_id={data["patient"]}).update(active=False)\nprint("revoked")\n')
        b.evaluate(doctor,'refreshAssistantAlerts()');b.wait(doctor,'state.assistantAlerts.items.length===0')
        check('old session denied after relationship revoke',api(doctor,f'/api/doctor/assistant-notifications/{event}')['status']==404)

        # Promise resolving after logout must not restore account data.
        b.viewport(pa,1440)
        route(pa,'/patient/assistant')
        script(pa,"window.lateOriginal=window.fetch;window.fetch=(path,options)=>path==='/api/me/assistant/messages'&&options?.method==='POST'?new Promise(resolve=>window.resolveLateAssistant=resolve):window.lateOriginal(path,options)")
        fill(pa,'assistantText','Поздний синтетический ответ');b.click(pa,'#assistantForm button[type=submit]');b.click(pa,'[data-action="logout"]')
        b.wait(pa,'!sessionUser&&!loading')
        script(pa,"window.resolveLateAssistant(new Response(JSON.stringify({id:99999,text:'OLD_PRIVATE',reply:'OLD_REPLY',status:'completed',created_at:new Date().toISOString()}),{status:201,headers:{'Content-Type':'application/json'}}));window.fetch=window.lateOriginal")
        time.sleep(.2)
        check('logout clears chat and ignores late response',b.evaluate(pa,'state.assistant.items.length===0&&!state.assistant.draft&&!document.body.textContent.includes("OLD_PRIVATE")'))
        check('template remains disabled',not api(other,'/api/doctor/assistant-notifications')['body']['automatic_detection_enabled'])
        metadata['browser']=b.call('session.status',{})
    finally:
        try:
            op(f'from accounts.models import User\nfrom care.models import CareRelationship\nUser.objects.filter(pk__in={[data["patient"],data["doctor"],data["other"]]}).update(is_active=False)\nCareRelationship.objects.filter(patient_id={data["patient"]}).update(active=False)\nprint("synthetic accounts disabled; audit and events retained")\n')
        finally:
            b.close()
            Path(args.output).write_text(json.dumps({'checks':results,'metadata':metadata},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':len(results),'metadata':metadata},ensure_ascii=False))


if __name__=='__main__':
    main()
