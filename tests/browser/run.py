"""WORK-0008: isolated synthetic UI acceptance using Firefox WebDriver BiDi.

Run against a dedicated Compose project, never a real patient environment.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time
import urllib.request
import urllib.error
import hashlib
from bidi import Browser

ROOT=Path(__file__).resolve().parents[2]

def internet_check(args):
    """WORK-0014: explicit synthetic acceptance of the approved public pilot."""
    base = 'https://94.103.3.149'
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes', 'veganmedtech-server']
    password = secrets.token_urlsafe(24)
    suffix = 'work0019-' + secrets.token_hex(5)
    emails = []
    results = []
    b = Browser(args.bidi_port, accept_insecure=False)
    def check(name, value):
        results.append(dict(name=name, passed=bool(value)))
        if not value: raise AssertionError(name)
    def operator(*command):
        subprocess.run(ssh + ['docker', 'exec', '-i', 'veganmedtech-app-1', 'python', 'manage.py', *command],
                       check=True, stdout=subprocess.DEVNULL)
    def route(c, path):
        b.evaluate(c, 'location.hash=' + json.dumps(path));time.sleep(.25);b.wait(c, '!loading')
    def fill(c, values):
        b.evaluate(c, '(()=>{const values='+json.dumps(values)+';for(const [id,value] of Object.entries(values)){const el=document.getElementById(id);el.value=value;el.dispatchEvent(new Event("input",{bubbles:true}));}return true;})()')
    def submit(c, selector='#accountForm button[type=submit]'):
        b.click(c, selector);b.wait(c, '!authBusy')
    def transition_check(c, role, width):
        """WORK-0019: verify the deployed DOM with controlled HTTPS responses."""
        if role=='patient':
            route(c,'/patient/report');fill(c,dict(reportText='Вымышленный черновик перехода WORK-0019'))
        data='/api/me/self-reports' if role=='patient' else '/api/patients'
        target='/patient/history' if role=='patient' else '/doctor/interactions'
        latest='/patient/films' if role=='patient' else '/doctor'
        menu='.mobile-menu' if width==390 else '.desktop-nav'
        b.evaluate(c,'''(()=>{window.deployFetch=fetch;window.deployHeld=[];window.deployWrites=[];window.deployHolding=true;
            window.deployMain=document.querySelector('#mainContent');window.deployScreens=[];
            window.deployObserver=new MutationObserver(()=>deployScreens.push(document.querySelector('#pageTitle')?.textContent));
            deployObserver.observe(document.querySelector('#app'),{subtree:true,childList:true});
            const data=DATA;window.fetch=(path,options)=>{
                if(options?.method && options.method!=='GET')deployWrites.push(path);
                return deployFetch(path,options).then(response=>deployHolding&&['/api/me',data].includes(path)?
                    new Promise(resolve=>deployHeld.push({path,release:()=>resolve(response)})):response);};return true;})()'''.replace('DATA',json.dumps(data)))
        if width==390:b.click(c,'.mobile-menu summary')
        b.click(c,menu+' a[href="#'+target+'"]');b.wait(c,'deployHeld.length===1')
        check(f'HTTPS transition retains page {role} {width}',b.evaluate(c,
            'document.querySelector("#mainContent")===deployMain && deployMain.inert && deployMain.getAttribute("aria-busy")==="true" && !!document.querySelector("#routeStatus[role=status]") && !deployScreens.includes("Загружаем…")'))
        if role=='patient':
            b.evaluate(c,'document.querySelector("#reportForm").requestSubmit()')
            check(f'HTTPS old form blocked {width}',b.evaluate(c,'deployWrites.length===0 && !state.pending'))
        b.screenshot(c,Path(args.output).with_name(f'https-{role}-pending-{width}.png'))
        b.evaluate(c,'deployHeld[0].release()');b.wait(c,'deployHeld.length===2')
        check(f'HTTPS transition waits for data {role} {width}',b.evaluate(c,
            'loading && document.querySelector("#mainContent")===deployMain'))
        # A later menu selection can finish while the earlier data is still held.
        b.click(c,menu+' a[href="#'+latest+'"]')
        b.wait(c,'deployHeld.filter(x=>x.path==="/api/me").length===2')
        b.evaluate(c,'deployHeld.filter(x=>x.path==="/api/me")[1].release()')
        if role=='doctor':
            b.wait(c,'deployHeld.filter(x=>x.path==="/api/patients").length===2')
            b.evaluate(c,'deployHeld.filter(x=>x.path==="/api/patients")[1].release()')
        b.wait(c,'!loading');b.evaluate(c,'deployHeld.filter(x=>x.path==='+json.dumps(data)+')[0].release()');time.sleep(.2)
        check(f'HTTPS latest selection and focus {role} {width}',b.evaluate(c,
            'location.hash==='+json.dumps('#'+latest)+' && !routeError && !deployScreens.includes("Загружаем…") && document.activeElement===document.querySelector("#pageTitle") && !document.querySelector("#routeStatus") && !document.querySelector("#mainContent").inert'))
        b.evaluate(c,'(()=>{window.deployHolding=false;window.fetch=deployFetch;deployHeld.forEach(x=>x.release());deployObserver.disconnect();return true;})()')
        b.screenshot(c,Path(args.output).with_name(f'https-{role}-ready-{width}.png'))
    def mail_link(email, segment):
        code = '''import json,re,urllib.request,time
email=EMAIL;segment=SEGMENT
for attempt in range(40):
 with urllib.request.urlopen('http://127.0.0.1:18025/api/v1/messages') as r: messages=json.load(r)['messages']
 for msg in messages:
  if any(x.get('Address')==email for x in msg.get('To',[])):
   with urllib.request.urlopen('http://127.0.0.1:18025/api/v1/message/'+msg['ID']) as r: body=json.load(r)
   found=re.search(r'https?://[^\\s<>]+/#/'+segment+r'/[^\\s<>]+',body.get('Text',''))
   if found: print(found.group(0));raise SystemExit(0)
 time.sleep(.25)
raise SystemExit('Synthetic email was not received')
'''.replace('EMAIL',repr(email)).replace('SEGMENT',repr(segment))
        return subprocess.check_output(ssh + ['python3 -'], input=code.encode()).decode().strip()
    def create(role, label):
        email = label + '-' + suffix + '@example.test';emails.append(email)
        c=b.context(private=True);b.viewport(c,1440);b.navigate(c,base+'/#/register/'+role);b.wait(c,'!loading')
        fill(c,dict(profileName='Проверка '+label,accountEmail=email,password=password,password_repeat=password));submit(c)
        check(label+' registration',bool(b.evaluate(c,'authNotice')) and not b.evaluate(c,'authError'))
        check(label+' operator confirmation notice',b.evaluate(c,'authNotice.includes("организатор") && authNotice.includes("не отправляется")'))
        check(label+' unverified module denied',b.evaluate(c,'(async()=>{const r=await fetch("/api/questionnaires/module");return [401,403].includes(r.status);})()'))
        url=mail_link(email,'verify-email');check(label+' HTTPS confirmation link',url.startswith(base+'/#/verify-email/'))
        b.navigate(c,url);b.wait(c,'!loading');submit(c);check(label+' confirmation',not b.evaluate(c,'authError'))
        route(c,'/login');fill(c,dict(accountEmail=email,password=password));submit(c)
        b.wait(c,'!!sessionUser && !loading && readRoute().view!=="login"')
        check(label+' login',b.evaluate(c,'sessionUser.role')==role)
        return c,email
    try:
        with urllib.request.urlopen(base) as response:
            check('public page without Basic Auth',response.status==200 and not response.headers.get('WWW-Authenticate'))
        digest=hashlib.md5((ROOT/'frontend/static/js/questionnaires.js').read_bytes(),usedforsecurity=False).hexdigest()[:12]
        for name in ['questionnaires.js',f'questionnaires.{digest}.js']:
            for extension in ['', '.gz', '.br']:
                try:urllib.request.urlopen(base+'/static/js/'+name+extension);status=200
                except urllib.error.HTTPError as error:status=error.code
                check('no public module '+name+extension,status==404)
        anonymous=b.context(private=True);b.navigate(anonymous,base+'/#/patient/questionnaires');b.wait(anonymous,'!loading')
        check('anonymous questionnaire hash requires app login',b.evaluate(anonymous,'!sessionUser && !window.CompassQuestionnaires && !!document.querySelector("#accountForm")'))
        pa,pe=create('patient','patient-a');pb,pbe=create('patient','patient-b');da,de=create('doctor','doctor')
        check('doctor waits for operator',b.evaluate(da,'!sessionUser.doctor_approved'))
        operator('doctor_access','approve',de);operator('care_relationship','assign',pe,de)
        b.evaluate(da,'loadRoute()');b.wait(da,'!loading')
        check('doctor sees own patient',b.evaluate(da,'people.length===1'))
        route(pa,'/patient/report');fill(pa,dict(reportText='Вымышленная HTTPS-запись WORK-0014'));submit(pa,'#reportForm button[type=submit]')
        b.wait(pa,'readRoute().view==="history" && !loading')
        b.wait(pa,'document.body.innerText.includes("HTTPS-запись WORK-0014")')
        check('patient saves report',b.evaluate(pa,'document.body.innerText.includes("HTTPS-запись WORK-0014")'))
        pid=b.evaluate(pa,'sessionUser.id');other=b.evaluate(pb,'sessionUser.id')
        route(da,f'/doctor/patients/{pid}')
        check('independent doctor reads report',b.evaluate(da,'document.body.innerText.includes("HTTPS-запись WORK-0014")'))
        route(da,f'/doctor/patients/{other}')
        check('foreign patient denied',b.evaluate(da,'!!routeError && state.reports.length===0'))
        check('patient cannot read another patient',b.evaluate(pa,'(async()=>{try{await CompassAPI.request("/api/patients/'+str(other)+'/self-reports");return false;}catch(e){return [403,404].includes(e.status);}})()'))
        b.navigate(pa,base+'/#/patient/history');b.wait(pa,'!loading')
        check('report survives reload',b.evaluate(pa,'state.reports.length===1'))
        cookies=b.call('storage.getCookies',{'partition':{'type':'context','context':pa}})['cookies']
        session=next(x for x in cookies if x['name']=='sessionid')
        check('Secure HttpOnly session',session['secure'] and session['httpOnly'])
        check('browser HTTPS and secure context',b.evaluate(pa,'location.protocol==="https:" && window.isSecureContext'))
        check('CSRF rejection over public HTTPS',b.evaluate(pa,'(async()=>{const r=await fetch("/api/me/self-reports",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:"invalid",observed_at:new Date().toISOString()})});return r.status===403;})()'))
        # The raw/hashed data module is never public; authenticated delivery is role checked.
        check('doctor cannot fetch questionnaire module',b.evaluate(da,'(async()=>{const r=await fetch("/api/questionnaires/module");return r.status===403;})()'))
        check('patient module is private',b.evaluate(pa,'(async()=>{const r=await fetch("/api/questionnaires/module");return r.status===200 && r.headers.get("Cache-Control")==="no-store" && (await r.text()).includes("CompassQuestionnaires");})()'))
        check('module not eagerly loaded',b.evaluate(pa,'!window.CompassQuestionnaires'))
        b.evaluate(pa,'''(()=>{window.appendOriginal=document.head.appendChild;document.head.appendChild=function(el){if(el.src?.endsWith('/api/questionnaires/module'))el.src='/api/questionnaires/missing';return window.appendOriginal.call(this,el);};return true;})()''')
        route(pa,'/patient/questionnaires')
        b.wait(pa,'!loading && !!routeError')
        check('module failure offers retry',b.evaluate(pa,'!!document.querySelector("[data-api-retry]") && !document.querySelector("#questionnaireForm")'))
        b.evaluate(pa,'document.head.appendChild=window.appendOriginal')
        b.click(pa,'[data-api-retry]');b.wait(pa,'!loading && !routeError && !!window.CompassQuestionnaires')
        check('module retry loads four questionnaires',b.evaluate(pa,'CompassQuestionnaires.list.length===4 && document.querySelectorAll(".q-card").length===4'))
        for tool in ['lsia','bipq','temmo','stolin']:
            route(pa,'/patient/questionnaires/'+tool)
            b.click(pa,'[data-q-action=start]')
            check('questionnaire starts '+tool,b.evaluate(pa,'!!document.querySelector("#questionnaireForm") && !routeError'))
            b.evaluate(pa,'document.querySelector("#questionnaireForm").requestSubmit()')
            check('questionnaire requires answer '+tool,b.evaluate(pa,'!!document.querySelector("#qError:not([hidden])") && !document.querySelector(".q-result-hero")'))
            completed=b.evaluate(pa,'''(()=>{let steps=0;while(document.querySelector('#questionnaireForm') && steps++<60){document.querySelector('[data-q-answer]')?.click();document.querySelector('#questionnaireForm').requestSubmit();}return !!document.querySelector('.q-result-hero') && !document.querySelector('#questionnaireForm') && !routeError;})()''')
            check('questionnaire completes '+tool,completed)
        # Delay completion of a real, authorized module request until after logout.
        b.evaluate(pb,'''(()=>{window.appendOriginal=document.head.appendChild;document.head.appendChild=function(el){if(el.src?.endsWith('/api/questionnaires/module')){const done=el.onload;el.onload=()=>{window.moduleArrived=true;setTimeout(done,900);};}return window.appendOriginal.call(this,el);};location.hash='/patient/questionnaires';return true;})()''')
        b.wait(pb,'window.moduleArrived===true')
        b.evaluate(pb,'(()=>{state.questionnaires={synthetic:{answers:[1]}};return logout();})()');b.wait(pb,'!loading && !sessionUser')
        time.sleep(1.1)
        check('late module cannot restore personal state',b.evaluate(pb,'!sessionUser && Object.keys(state.questionnaires).length===0 && !document.querySelector("#questionnaireForm") && !!document.querySelector("#accountForm")'))
        b.evaluate(pb,'document.head.appendChild=window.appendOriginal')
        check('module denied after logout',b.evaluate(pb,'(async()=>{const r=await fetch("/api/questionnaires/module");return r.status===401;})()'))
        for width in [1440,390]:
            for c,paths in [(pa,['/patient','/patient/report','/patient/history','/patient/questionnaires']), (da,['/doctor',f'/doctor/patients/{pid}'])]:
                b.viewport(c,width)
                for path in paths:
                    route(c,path);check(f'layout {width} {path}',b.evaluate(c,'!!document.querySelector("#pageTitle") && document.documentElement.scrollWidth<=innerWidth+1 && !routeError'))
            b.screenshot(pa,Path(f'/tmp/work0014-patient-{width}.png'))
            b.screenshot(da,Path(f'/tmp/work0014-doctor-{width}.png'))
            transition_check(pa,'patient',width)
            transition_check(da,'doctor',width)
        route(pa,'/patient/report')
        b.call('input.performActions',{'context':pa,'actions':[{'type':'key','id':'keyboard','actions':[{'type':'keyDown','value':'\ue004'},{'type':'keyUp','value':'\ue004'}]}]})
        check('keyboard navigation',b.evaluate(pa,'document.activeElement!==document.body'))
        b.evaluate(pb,'logout()');b.wait(pb,'!loading && !sessionUser');route(pb,'/password/request')
        fill(pb,dict(accountEmail=pbe));submit(pb);check('password request UI',bool(b.evaluate(pb,'authNotice')))
        url=mail_link(pbe,'password/reset');check('HTTPS reset link',url.startswith(base+'/#/password/reset/'))
        b.navigate(pb,url);b.wait(pb,'!loading');fill(pb,dict(password=password+'NEW',password_repeat=password+'NEW'));submit(pb)
        check('password reset UI',not b.evaluate(pb,'authError'))
        route(pa,'/patient/report')
        b.evaluate(pa,'''(()=>{window.exitFetch=fetch;window.releaseExit=null;let held=false;
            window.fetch=(path,options)=>exitFetch(path,options).then(response=>path==='/api/me'&&!held?
                (held=true,new Promise(resolve=>window.releaseExit=()=>resolve(response))):response);
            location.hash='/patient/films';return true;})()''')
        b.wait(pa,'!!releaseExit');b.click(pa,'.mobile-menu summary');b.click(pa,'.mobile-menu [data-action=logout]')
        b.wait(pa,'!loading && !sessionUser');b.evaluate(pa,'(()=>{window.fetch=exitFetch;releaseExit();return true;})()');time.sleep(.2)
        check('HTTPS logout during transition clears previous DOM',b.evaluate(pa,'!sessionUser && !document.querySelector(".workspace") && !!document.querySelector("#accountForm")'))
        check('logout clears personal state',b.evaluate(pa,'state.reports.length===0 && !state.draft.text'))
        fill(pa,dict(accountEmail=pbe,password=password+'NEW'));submit(pa)
        b.wait(pa,'!!sessionUser && !loading && readRoute().view!=="login"')
        check('new password and account switch',b.evaluate(pa,'sessionUser.id')==other)
        route(pa,'/patient/questionnaires')
        check('account switch clears previous questionnaire answers',b.evaluate(pa,'Object.keys(state.questionnaires).length===0 && document.querySelectorAll(".q-card").length===4'))
        b.evaluate(da,'logout()');b.wait(da,'!loading && !sessionUser')
        check('doctor logout',b.evaluate(da,'people.length===0 && state.reports.length===0 && !!document.querySelector("#accountForm")'))
        calc=b.context(private=True);b.navigate(calc,(ROOT/'frontend/tests/questionnaires.html').as_uri());b.wait(calc,'typeof testResults!=="undefined"')
        check('219 calculation regressions',b.evaluate(calc,'({passed:testResults.passed,failed:testResults.failed})')==dict(passed=219,failed=0))
    finally:
        b.close()
        # Preserve audit actors/events; deactivate only this run's synthetic accounts.
        code='''from accounts.models import User
from reports.models import SelfReport
from care.models import CareRelationship
from django.db.models import Q
users=User.objects.filter(email__in=EMAILS)
SelfReport.objects.filter(patient__in=users).delete()
CareRelationship.objects.filter(Q(patient__in=users)|Q(doctor__in=users)).update(active=False)
users.update(is_active=False)
'''.replace('EMAILS',repr(emails))
        subprocess.run(ssh+['docker exec -i veganmedtech-app-1 python manage.py shell'],input=code.encode(),check=True,stdout=subprocess.DEVNULL)
        out=Path(args.output if args.output!='/tmp/work0008-browser-results.json' else '/tmp/work0014-browser-results.json')
        out.write_text(json.dumps(dict(base_url=base,accept_insecure_certs=False,checks=results),ensure_ascii=False,indent=2)+'\n')
    print('WORK-0014 pilot browser checks passed:',len(results),flush=True)


def mailpit_check(args):
    """WORK-0015: operator mailbox via public HTTPS; never print credentials/links."""
    import base64
    import websocket
    origin='https://94.103.3.149:8443';app='https://94.103.3.149'
    ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no','-o','ClearAllForwardings=yes','veganmedtech-server']
    private=json.loads(subprocess.check_output(ssh+['cat','/opt/veganmedtech/config/mailpit-access.json']))
    authorization='Basic '+base64.b64encode((private['username']+':'+private['password']).encode()).decode()
    password=secrets.token_urlsafe(24);email='work0015-'+secrets.token_hex(6)+'@example.test'
    checks=[];b=None;registered=False;phase='transport'
    def check(name,value):
        checks.append(dict(name=name,passed=bool(value)))
        if not value:raise AssertionError(name)
    def get(path,auth=authorization):
        headers={'Authorization':auth} if auth else {}
        try:return urllib.request.urlopen(urllib.request.Request(origin+path,headers=headers),timeout=10)
        except urllib.error.HTTPError as error:return error
    def letter(segment):
        for _ in range(40):
            with get('/api/v1/messages?limit=1000') as r:messages=json.load(r)['messages']
            for message in messages:
                if not any(to.get('Address')==email for to in message.get('To',[])):continue
                with get('/api/v1/message/'+message['ID']) as r:body=json.load(r)
                match=re.search(r'https://94\.103\.3\.149/#/'+segment+r'/[^\s<>]+',body.get('Text',''))
                if match:return message['ID'],match.group(0)
            time.sleep(.25)
        raise AssertionError('Own synthetic letter not received')
    def fill(c,values):
        b.evaluate(c,'(()=>{for(const [id,value] of Object.entries('+json.dumps(values)+')){const el=document.getElementById(id);el.value=value;el.dispatchEvent(new Event("input",{bubbles:true}));}return true;})()')
    def submit(c):b.click(c,'#accountForm button[type=submit]');b.wait(c,'!authBusy')
    def route(c,path):b.evaluate(c,'location.hash='+json.dumps(path));time.sleep(.25);b.wait(c,'!loading')
    try:
        with get('/') as r:
            html=r.read().decode();check('trusted HTTPS operator UI',r.status==200 and 'Mailpit' in html)
            check('mailbox no-store',r.headers.get('Cache-Control')=='no-store')
        assets=re.findall(r'(?:src|href)="(/[^"?]+\.(?:js|css))(?:\?[^\"]*)?"',html)[:3]
        check('actual Mailpit assets found',bool(assets))
        for auth,label in [(None,'anonymous'),('Basic '+base64.b64encode(b'operator:incorrect').decode(),'wrong password')]:
            for path in ['/', '/api/v1/messages','/api/v1/info','/api/events',*assets]:
                with get(path,auth) as r:check(label+' blocked '+path,r.status==401)
            try:
                ws=websocket.create_connection(origin.replace('https:','wss:')+'/api/events',header={'Authorization':auth} if auth else {},origin=origin,timeout=8)
            except websocket.WebSocketBadStatusException as error:check(label+' websocket blocked',error.status_code==401)
            else:ws.close();check(label+' websocket blocked',False)
        ws=websocket.create_connection(origin.replace('https:','wss:')+'/api/events',header={'Authorization':authorization},origin=origin,timeout=8)
        check('operator websocket upgrade',ws.getstatus()==101);ws.close()
        try:
            ws=websocket.create_connection(origin.replace('https:','wss:')+'/api/events',header={'Authorization':authorization},origin='https://foreign.example.test',timeout=8)
        except websocket.WebSocketBadStatusException as error:check('foreign websocket Origin blocked',error.status_code==403)
        else:ws.close();check('foreign websocket Origin blocked',False)
        phase='browser registration'
        b=Browser(args.bidi_port,accept_insecure=False,basic_auth=dict(origin=origin,username=private['username'],password=private['password']))
        mailbox=b.context(private=True);b.navigate(mailbox,origin+'/');b.wait(mailbox,'!!document.querySelector('+json.dumps('input[placeholder="Search mailbox"]')+') && !document.body.innerText.includes("Loading messages...")')
        started=b.evaluate(mailbox,'performance.timeOrigin')
        patient=b.context(private=True);b.navigate(patient,app+'/#/register/patient');b.wait(patient,'!loading')
        fill(patient,dict(profileName='Проверка Mailpit',accountEmail=email,password=password,password_repeat=password));submit(patient)
        registered=True;check('synthetic registration',b.evaluate(patient,'!!authNotice && !authError'))
        message_id,url=letter('verify-email')
        b.wait(mailbox,'!!document.querySelector('+json.dumps('a[href="/view/'+message_id+'"]')+')')
        check('new letter appears without reload',b.evaluate(mailbox,'performance.timeOrigin')==started)
        b.click(mailbox,'a[href="/view/'+message_id+'"]');b.wait(mailbox,'document.body.innerText.includes('+json.dumps(email)+')')
        check('operator opens own letter',b.evaluate(mailbox,'location.pathname')=='/view/'+message_id)
        for width in [1440,390]:
            b.viewport(mailbox,width);time.sleep(.2)
            check('Mailpit layout '+str(width),b.evaluate(mailbox,'document.documentElement.scrollWidth<=innerWidth+1 && !!document.querySelector('+json.dumps('[title="Return to messages"]')+')'))
        b.navigate(patient,url);b.wait(patient,'!loading');submit(patient);check('email confirmation via mailbox link',b.evaluate(patient,'!authError && !!authNotice'))
        route(patient,'/login');fill(patient,dict(accountEmail=email,password=password));submit(patient);b.wait(patient,'!!sessionUser && !loading');check('confirmed account login',True)
        b.evaluate(patient,'logout()');b.wait(patient,'!loading && !sessionUser');route(patient,'/password/request')
        phase='password reset'
        b.navigate(mailbox,origin+'/');b.wait(mailbox,'!document.body.innerText.includes("Loading messages...")')
        started=b.evaluate(mailbox,'performance.timeOrigin')
        fill(patient,dict(accountEmail=email));submit(patient);check('password request',b.evaluate(patient,'!!authNotice && !authError'))
        message_id,url=letter('password/reset')
        b.wait(mailbox,'!!document.querySelector('+json.dumps('a[href="/view/'+message_id+'"]')+')')
        check('reset letter arrives through live mailbox',b.evaluate(mailbox,'performance.timeOrigin')==started)
        b.click(mailbox,'a[href="/view/'+message_id+'"]');b.wait(mailbox,'document.body.innerText.includes('+json.dumps(email)+')')
        b.navigate(patient,url);b.wait(patient,'!loading');fill(patient,dict(password=password+'NEW',password_repeat=password+'NEW'));submit(patient);check('password reset via mailbox link',b.evaluate(patient,'!authError && !!authNotice'))
        route(patient,'/login');fill(patient,dict(accountEmail=email,password=password+'NEW'));submit(patient);b.wait(patient,'!!sessionUser && !loading');check('new password works',True)
    except Exception as error:
        # Tracebacks must never interpolate private credentials or token URLs.
        raise RuntimeError('Mailpit check failed in '+phase+' ('+type(error).__name__+')') from None
    finally:
        if b:b.close()
        if registered:
            code='from accounts.models import User; User.objects.filter(email='+repr(email)+').update(is_active=False)'
            subprocess.run(ssh+['docker exec -i veganmedtech-app-1 python manage.py shell'],input=code.encode(),check=True,stdout=subprocess.DEVNULL)
        out=Path(args.output if args.output!='/tmp/work0008-browser-results.json' else '/tmp/work0015-mailpit-results.json')
        out.write_text(json.dumps(dict(origin=origin,accept_insecure_certs=False,checks=checks),ensure_ascii=False,indent=2)+'\n')
    print('WORK-0015 Mailpit checks passed:',len(checks),flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://localhost:18008')
    parser.add_argument('--mail-url',default='http://localhost:18025')
    parser.add_argument('--compose-env-file')
    parser.add_argument('--internet-check',action='store_true')
    parser.add_argument('--mailpit-check',action='store_true')
    parser.add_argument('--navigation-only',action='store_true')
    parser.add_argument('--project',default='veganmedtech-work0008-test')
    parser.add_argument('--bidi-port',type=int,default=19228)
    parser.add_argument('--output',default='/tmp/work0008-browser-results.json')
    args=parser.parse_args()
    if args.mailpit_check:
        return mailpit_check(args)
    if args.internet_check:
        return internet_check(args)
    if not args.compose_env_file:
        parser.error("--compose-env-file is required for the local synthetic suite")
    if args.project not in {'veganmedtech-work0008-test','veganmedtech-work0018-test','veganmedtech-work0020-test'}:raise SystemExit('Only an explicitly named synthetic test project is permitted')
    subprocess.run(['docker','compose','--env-file',args.compose_env_file,'-p',args.project,'exec','-T','app','python','manage.py','shell','-c','from django.core.cache import cache;cache.clear()'],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    base=args.base_url.rstrip('/')
    password=secrets.token_urlsafe(24)
    suffix=secrets.token_hex(5)
    results=[]
    b=Browser(args.bidi_port)
    def check(name,value):
        results.append({'name':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def wait(c,expr,timeout=20):b.wait(c,expr,timeout)
    def route(c,path):
        b.evaluate(c,'location.hash='+json.dumps(path));wait(c,'!loading')
        # A hash change schedules navigation asynchronously; wait for its new load too.
        time.sleep(.2);wait(c,'!loading')
    def fill(c,values):
        b.evaluate(c,'(()=>{const values='+json.dumps(values)+';for(const [id,value] of Object.entries(values)){const el=document.getElementById(id);el.value=value;el.dispatchEvent(new Event("input",{bubbles:true}));}return true;})()')
    def submit(c,selector='#accountForm button[type=submit]'):
        b.evaluate(c,'document.querySelector('+json.dumps(selector)+').click()')
    def mail_link(email,segment):
        for _ in range(80):
            with urllib.request.urlopen(args.mail_url+'/api/v1/messages') as response:messages=json.load(response)['messages']
            for msg in messages:
                if any(x.get('Address')==email for x in msg.get('To',[])):
                    with urllib.request.urlopen(args.mail_url+'/api/v1/message/'+msg['ID']) as response:body=json.load(response)
                    text=body.get('Text','')
                    found=re.search(r'https?://[^\s<>]+/#/'+segment+r'/[^\s<>]+',text)
                    if found:return found.group(0)
            time.sleep(.1)
        raise AssertionError('Synthetic email not received')
    def operator(*command):
        subprocess.run(['docker','compose','--env-file',args.compose_env_file,'-p',args.project,'--profile','dev','exec','-T','app','python','manage.py',*command],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    def create(role,label):
        c=b.context(private=True);b.viewport(c,1440);b.navigate(c,base+'/#/register/'+role);wait(c,'!loading')
        email=f'{label}-{suffix}@example.test'
        fill(c,{'profileName':'Учебный '+label,'accountEmail':email,'password':password,'password_repeat':password});submit(c)
        wait(c,'!authBusy');check(role+' signup',bool(b.evaluate(c,'authNotice')) and not b.evaluate(c,'authError'))
        url=mail_link(email,'verify-email');b.navigate(c,url);wait(c,'!loading');submit(c);wait(c,'!authBusy')
        check(role+' email confirmation UI',not b.evaluate(c,'authError'))
        route(c,'/login');fill(c,{'accountEmail':email,'password':password});submit(c)
        wait(c,'!!sessionUser && !loading && readRoute().view !== "login"')
        check(role+' verified login',b.evaluate(c,'sessionUser.role')==role)
        return c,email
    def navigation_checks(pa, pe, pb, pbe, da):
        """TEST-001-43: held network responses exercise real DOM and route races."""
        def observe(c):
            b.evaluate(c, '''(()=>{window.navScreens=[];window.navObserver?.disconnect();
                window.navObserver=new MutationObserver(()=>navScreens.push(document.querySelector('#pageTitle')?.textContent));
                navObserver.observe(document.querySelector('#app'),{childList:true,subtree:true});return true;})()''')
        def hold(c, paths):
            b.evaluate(c, '''(()=>{window.navFetch=fetch;window.navHeld=[];window.navWrites=[];window.navHolding=true;window.navMain=document.querySelector('#mainContent');
                const paths=PATHS;window.fetch=(path,options)=>{
                    if(options?.method && options.method!=='GET')navWrites.push(path);
                    const result=navFetch(path,options);
                    return paths.includes(path)?result.then(response=>navHolding?new Promise(resolve=>navHeld.push({path,release:()=>resolve(response)})):response):result;
                };return true;})()'''.replace('PATHS',json.dumps(paths)))
        def release(c, path='/api/me', index=0):
            wait(c,'navHeld.filter(x=>x.path==='+json.dumps(path)+').length>'+str(index))
            b.evaluate(c,'navHeld.filter(x=>x.path==='+json.dumps(path)+')['+str(index)+'].release()')
        def restore(c):
            b.evaluate(c,'(()=>{window.navHolding=false;window.fetch=navFetch;navHeld.forEach(x=>x.release());return true;})()')
        def login(c, email):
            route(c,'/login');fill(c,dict(accountEmail=email,password=password));submit(c)
            wait(c,'!!sessionUser && !loading && readRoute().view!=="login"')
        pid=b.evaluate(pa,'sessionUser.id')
        for c,role,target in [(pa,'patient','/patient/films'),(da,'doctor','/doctor/interactions')]:
            observe(c)
            for width in [1440,768,390]:
                b.viewport(c,width);route(c,'/'+role);hold(c,['/api/me'])
                menu='.mobile-menu' if width==390 else '.desktop-nav'
                if width==390:b.click(c,'.mobile-menu summary')
                b.click(c,menu+' a[href="#'+target+'"]')
                wait(c,'navHeld.length===1')
                check(f'navigation retains cabinet {role} {width}',b.evaluate(c,
                    'document.querySelector("#mainContent")===navMain && !document.body.innerText.includes("Загружаем…")'))
                check(f'navigation busy status {role} {width}',b.evaluate(c,
                    'navMain.inert && navMain.getAttribute("aria-busy")==="true" && !!document.querySelector("#routeStatus[role=status]")'))
                b.evaluate(c,'render()')
                check(f'navigation background render {role} {width}',b.evaluate(c,'document.querySelector("#mainContent")===navMain'))
                if width in [390,1440]:b.screenshot(c,Path(args.output).with_name(f'{role}-pending-{width}.png'))
                release(c);wait(c,'!loading')
                check(f'navigation ready focus {role} {width}',b.evaluate(c,
                    'document.activeElement===document.querySelector("#pageTitle") && !document.querySelector("#routeStatus") && !document.querySelector("#mainContent").inert'))
                check(f'navigation active item {role} {width}',b.evaluate(c,
                    '!!document.querySelector('+json.dumps(menu+' a[aria-current=page][href="#'+target+'"]')+')'))
                restore(c)
            paths=(['/patient','/patient/assistant','/patient/questionnaires','/patient/notifications','/patient/doctors',
                '/patient/chat/doctor-a','/patient/medication','/patient/games','/patient/films','/patient/sounds','/patient/report','/patient/history']
                if role=='patient' else ['/doctor',f'/doctor/patients/{pid}',f'/doctor/chat/{pid}','/doctor/assistant-alerts','/doctor/interactions'])
            for width in [1440,768,390]:
                b.viewport(c,width)
                for path in paths:
                    route(c,path)
                    check(f'navigation no splash {width} {path}',b.evaluate(c,
                        '!navScreens.includes("Загружаем…") && !routeError && document.documentElement.scrollWidth<=innerWidth+1'))
            for action in ['back','forward']:
                b.evaluate(c,'history.'+action+'()');time.sleep(.2);wait(c,'!loading')
                check(f'navigation history {role} {action}',b.evaluate(c,'!navScreens.includes("Загружаем…") && !routeError'))
            # Check a data request independently of the session request.
            route(c,'/'+role);data_path='/api/me/self-reports' if role=='patient' else '/api/patients'
            hold(c,['/api/me',data_path]);b.evaluate(c,'location.hash='+json.dumps('/patient/history' if role=='patient' else f'/doctor/patients/{pid}'))
            release(c);wait(c,'navHeld.length===2')
            check('navigation waits for data '+role,b.evaluate(c,'loading && document.querySelector("#mainContent")===navMain'))
            release(c,data_path);wait(c,'!loading');restore(c)
            b.evaluate(c,'navObserver.disconnect()')
        route(pa,'/patient/report');fill(pa,{'reportText':'SYNTHETIC_TRANSITION_DRAFT'})
        hold(pa,['/api/me']);b.evaluate(pa,'location.hash="/patient/films"');wait(pa,'navHeld.length===1')
        b.click(pa,'#reportForm button[type=submit]')
        b.evaluate(pa,'document.querySelector("#reportForm").requestSubmit()')
        check('navigation blocks old form and writes',b.evaluate(pa,'navWrites.length===0 && !state.pending'))
        b.evaluate(pa,'document.querySelector("#reportText").focus()')
        check('navigation old input cannot receive focus',b.evaluate(pa,'document.activeElement.id!=="reportText"'))
        b.call('input.performActions',{'context':pa,'actions':[{'type':'key','id':'keyboard','actions':[{'type':'keyDown','value':'\ue004'},{'type':'keyUp','value':'\ue004'}]}]})
        check('navigation keyboard stays outside inert content',b.evaluate(pa,'!navMain.contains(document.activeElement)'))
        b.evaluate(pa,'location.hash="/patient/games"');wait(pa,'navHeld.length===2')
        b.evaluate(pa,'location.hash="/patient/sounds"');wait(pa,'navHeld.length===3')
        release(pa,index=2);wait(pa,'!loading');release(pa,index=1);release(pa,index=0);time.sleep(.15)
        check('navigation reverse responses keep latest route',b.evaluate(pa,'readRoute().view==="sounds" && document.title.startsWith("Звуки") && !routeError'))
        restore(pa)
        # A previous data response cannot overwrite a completed later route.
        route(pa,'/patient');hold(pa,['/api/me','/api/me/self-reports'])
        b.evaluate(pa,'location.hash="/patient/history"');release(pa);wait(pa,'navHeld.length===2')
        b.evaluate(pa,'location.hash="/patient/films"');release(pa,index=1);wait(pa,'!loading')
        release(pa,'/api/me/self-reports');time.sleep(.15)
        check('navigation ignores old data',b.evaluate(pa,'document.title.startsWith("Кино") && !routeError'))
        restore(pa)
        for status in [403,500,'network']:
            route(pa,'/patient/report')
            b.evaluate(pa,'''(()=>{window.errorFetch=fetch;window.fetch=(path,options)=>path==='/api/me'?
                FAILURE:errorFetch(path,options);return true;})()'''.replace('FAILURE',
                'Promise.reject(new TypeError("Synthetic network failure"))' if status=='network' else
                'Promise.resolve(new Response(JSON.stringify({error:{message:"Синтетическая ошибка"}}),{status:'+str(status)+'}))'))
            route(pa,'/patient/films')
            check('navigation failure closes old content '+str(status),b.evaluate(pa,'!!routeError && !document.querySelector("#reportForm") && !!document.querySelector("[data-api-retry]")'))
            b.evaluate(pa,'window.fetch=errorFetch');b.click(pa,'[data-api-retry]');wait(pa,'!loading')
            check('navigation retry '+str(status),b.evaluate(pa,'!routeError && document.title.startsWith("Кино")'))
        route(pa,'/patient/report')
        b.evaluate(pa,'CompassAPI.auth("auth/session",{method:"DELETE"})')
        hold(pa,['/api/me']);b.evaluate(pa,'location.hash="/patient/films"');release(pa);wait(pa,'!sessionUser && !loading')
        check('navigation expired session closes previous content',b.evaluate(pa,'!document.querySelector(".workspace") && !state.draft.text && !!document.querySelector("#accountForm")'))
        restore(pa);login(pa,pe)
        route(pa,'/patient/report');hold(pa,['/api/me'])
        b.evaluate(pa,'location.hash="/patient/films"');wait(pa,'navHeld.length===1')
        # Exit remains clickable even with a held transition response.
        b.click(pa,'.mobile-menu summary');b.click(pa,'.mobile-menu [data-action=logout]')
        wait(pa,'!sessionUser');restore(pa);wait(pa,'!loading');time.sleep(.15)
        check('navigation logout discards held response',b.evaluate(pa,'!sessionUser && !document.querySelector(".workspace") && state.draft.text===""'))
        login(pa,pe)
        # Real server-side account change while a previous cabinet is still displayed.
        route(pa,'/patient/report');fill(pa,{'reportText':'SYNTHETIC_OLD_OWNER'})
        b.evaluate(pa,'CompassAPI.auth("auth/session",{method:"DELETE"})')
        b.evaluate(pa,'CompassAPI.auth("auth/login",{method:"POST",body:'+json.dumps({'email':pbe,'password':password})+'})')
        hold(pa,['/api/me','/api/me/self-reports']);b.evaluate(pa,'location.hash="/patient/history"');release(pa)
        wait(pa,'navHeld.length===2')
        check('navigation different owner hides previous cabinet before data',b.evaluate(pa,
            '!navMain.isConnected && !document.body.innerText.includes("SYNTHETIC_OLD_OWNER") && state.draft.text===""'))
        release(pa,'/api/me/self-reports');wait(pa,'!loading');restore(pa)
        check('navigation changed owner ready',b.evaluate(pa,'sessionUser.id')==b.evaluate(pb,'sessionUser.id'))
        b.evaluate(pa,'logout()');wait(pa,'!sessionUser && !loading');login(pa,pe)
        route(pa,'/patient');route(da,'/doctor')
        print('Navigation retention, delays, races, failures, logout and owner change passed',flush=True)

    def session_checks(pa, pe, pb, pbe, da, de):
        """TEST-001-38: real sessions plus isolated transport failures, no stored credentials."""
        def login(c, email):
            route(c, '/login');fill(c, {'accountEmail':email,'password':password});submit(c)
            wait(c, '!!sessionUser && !loading && !authBusy && readRoute().view!=="login"')
        def switch(c):
            b.click(c, '[data-action=logout]');wait(c, '!sessionUser && !loading && !!document.querySelector("#accountForm")')
        def current(c):
            return b.evaluate(c, '''!!sessionUser && document.body.innerText.includes('Вы уже вошли') &&
                document.body.innerText.includes(sessionUser.name) &&
                document.body.innerText.includes(sessionUser.role==='doctor'?'Врач':'Пациент') &&
                !document.querySelector('#accountForm') && !!document.querySelector('[data-action=logout]') &&
                !!document.querySelector('a[href="#/'+sessionUser.role+'"]')''')
        # The installed allauth contract is deliberately asserted without echoing user payloads.
        for operation, body in [('auth/login', {'email':pbe,'password':password}),
                ('auth/signup', {'email':f'unused-{suffix}@example.test','password':password,
                    'display_name':'Учебная замена','role':'doctor'})]:
            response=b.evaluate(pa, 'CompassAPI.auth('+json.dumps(operation)+',{method:"POST",body:'+json.dumps(body)+'})')
            check('session contract '+operation+' HTTP 409 body {status:409}',response=={'status':409})
            check('session contract preserves patient',b.evaluate(pa, 'CompassAPI.request("/api/me").then(u=>u.id===sessionUser.id && u.role==="patient")'))
        public=['/','/login','/register/patient','/register/doctor']
        for c, role in [(pa,'patient'),(da,'doctor')]:
            b.evaluate(c, '''(()=>{window.sessionFetch=fetch;window.sessionPosts=0;window.fetch=(path,options)=>{
                if(options?.method==='POST' && (path.endsWith('/auth/login') || path.endsWith('/auth/signup')))sessionPosts++;
                return sessionFetch(path,options);};return true;})()''')
            for width in [1440,768,390]:
                b.viewport(c,width)
                for path in public:
                    route(c,path)
                    check(f'session current {role} {width} {path}',current(c))
                    check(f'session layout {role} {width} {path}',b.evaluate(c,'document.documentElement.scrollWidth<=innerWidth+1'))
                check(f'session long safe name {role} {width}',b.evaluate(c,'''(()=>{const name=sessionUser.name;
                    sessionUser.name='А'.repeat(40)+'<img src=x>';render();const ok=document.documentElement.scrollWidth<=innerWidth+1 &&
                    !document.querySelector('img[src=x]') && document.body.innerText.includes('<img src=x>');
                    sessionUser.name=name;render();return ok;})()'''))
            check('session browsing sends no auth POST '+role,b.evaluate(c,'sessionPosts===0'))
            b.screenshot(c,Path('/tmp/work0011-session-'+role+'.png'))
            b.evaluate(c,'window.fetch=window.sessionFetch')
            for path in public:
                b.navigate(c,base+'/#'+path);wait(c,'!loading')
                check('session reload '+role+' '+path,current(c))
            route(c,'/login');route(c,'/register/doctor')
            b.evaluate(c,'history.back()');time.sleep(.2);wait(c,'!loading')
            check('session Back '+role,b.evaluate(c,'readRoute().view==="login"') and current(c))
            b.evaluate(c,'history.forward()');time.sleep(.2);wait(c,'!loading')
            check('session Forward '+role,b.evaluate(c,'readRoute().view==="register"') and current(c))
            b.call('browsingContext.activate', {'context':c})
            b.evaluate(c,'document.querySelector("#pageTitle").focus()')
            b.call('input.performActions',{'context':c,'actions':[{'type':'key','id':'session-keyboard','actions':[
                {'type':'keyDown','value':'\ue004'},{'type':'keyUp','value':'\ue004'}]}]})
            check('session keyboard continue '+role,b.evaluate(c,'document.activeElement.getAttribute("href")==='+json.dumps('#/'+role)+' && document.activeElement.matches(":focus-visible")'))
            b.call('input.performActions',{'context':c,'actions':[{'type':'key','id':'session-keyboard','actions':[
                {'type':'keyDown','value':'\ue007'},{'type':'keyUp','value':'\ue007'}]}]})
            wait(c,'!loading && !publicViews.has(readRoute().view)')
            check('session keyboard opens own cabinet '+role,b.evaluate(c,'sessionUser.role===readRoute().role && !routeError'))
            route(c,'/login');b.evaluate(c,'document.querySelector("#pageTitle").focus()')
            b.call('input.performActions',{'context':c,'actions':[{'type':'key','id':'session-keyboard','actions':[
                {'type':'keyDown','value':'\ue004'},{'type':'keyUp','value':'\ue004'},
                {'type':'keyDown','value':'\ue004'},{'type':'keyUp','value':'\ue004'}]}]})
            check('session keyboard switch '+role,b.evaluate(c,'document.activeElement.dataset.action==="logout" && document.activeElement.matches(":focus-visible")'))
            b.call('input.performActions',{'context':c,'actions':[{'type':'key','id':'session-keyboard','actions':[
                {'type':'keyDown','value':' '},{'type':'keyUp','value':' '}]}]})
            wait(c,'!loading && !sessionUser && !!document.querySelector("#accountForm")')
            check('session keyboard logout confirmed '+role,b.evaluate(c,'fetch("/api/me").then(r=>r.status===401)'))
            login(c, pe if role=='patient' else de)
        print('Session routes, reload, history and keyboard passed',flush=True)
        operator('doctor_access','revoke',de)
        route(da,'/login');check('session revoked doctor public',current(da) and not b.evaluate(da,'sessionUser.doctor_approved'))
        route(da,'/doctor');check('session revoked doctor waits',b.evaluate(da,'document.body.innerText.includes("Заявка ожидает одобрения") && !people.length'))
        operator('doctor_access','approve',de);b.evaluate(da,'loadRoute()');wait(da,'!loading')
        check('session approved doctor refreshes cabinet',b.evaluate(da,'sessionUser.doctor_approved && people.length===1'))
        route(pa,'/doctor');check('session patient cannot choose doctor role',b.evaluate(pa,'sessionUser.role==="patient" && document.body.innerText.includes("Раздел недоступен")'))
        route(da,'/patient');check('session doctor cannot choose patient role',b.evaluate(da,'sessionUser.role==="doctor" && document.body.innerText.includes("Раздел недоступен")'))
        # Two actual tabs share a dedicated cookie container; the first keeps its old form.
        for path, email in [('/login',pe),('/register/patient',de),('/register/doctor',pe)]:
            stale=b.context(private=True);uc=b.user_contexts[-1]
            second=b.call('browsingContext.create',{'type':'tab','userContext':uc})['context'];b.created_contexts.append(second)
            b.navigate(stale,base+'/#'+path);wait(stale,'!loading')
            values={'accountEmail':pbe,'password':password}
            if path!='/login':values.update(profileName='Учебная замена',password_repeat=password)
            fill(stale,values)
            b.navigate(second,base+'/#/login');wait(second,'!loading');login(second,email)
            b.evaluate(stale,'''(()=>{window.conflictFetch=fetch;window.conflictTraffic=[];window.fetch=async(path,options)=>{
                const r=await conflictFetch(path,options);conflictTraffic.push({path,status:r.status});return r;};return true;})()''')
            submit(stale);wait(stale,'!authBusy && !loading')
            check('session stale tab recovers '+path,current(stale))
            check('session stale tab confirms me after 409 '+path,b.evaluate(stale,'''conflictTraffic.length===2 &&
                conflictTraffic[0].status===409 && conflictTraffic[1].path==='/api/me' && conflictTraffic[1].status===200'''))
            check('session stale tab keeps actual account '+path,b.evaluate(stale,'sessionUser.name')==b.evaluate(second,'sessionUser.name'))
        print('Real shared-cookie tab conflicts passed',flush=True)
        anonymous=b.context(private=True);b.navigate(anonymous,base+'/#/login');wait(anonymous,'!loading')
        for failure in ['unauthenticated','network','forbidden']:
            fill(anonymous,{'accountEmail':pe,'password':password})
            b.evaluate(anonymous,'''(()=>{window.failureFetch=fetch;window.failureCalls=0;window.fetch=(path,options)=>{
                failureCalls++;
                if(path.endsWith('/auth/login'))return Promise.resolve(new Response('{"status":409}',{status:409}));
                if(path==='/api/me' && '''+json.dumps(failure)+'''==='network')return Promise.reject(new TypeError('synthetic'));
                if(path==='/api/me' && '''+json.dumps(failure)+'''==='forbidden')return Promise.resolve(new Response('{}',{status:403}));
                return failureFetch(path,options);};return true;})()''')
            submit(anonymous);wait(anonymous,'!authBusy && !loading');time.sleep(.3)
            check('session conflict no false success '+failure,b.evaluate(anonymous,'!sessionUser && !!authError && !authNotice && !!document.querySelector("#accountForm") && failureCalls===2'))
            b.evaluate(anonymous,'window.fetch=window.failureFetch')
        # A failed logout must retain the verified account and offer an explicit retry.
        for failure in ['network','403','503']:
            route(pa,'/login')
            b.evaluate(pa,'''(()=>{window.logoutFetch=fetch;window.fetch=(path,options)=>{
                if(options?.method==='DELETE')return '''+('Promise.reject(new TypeError("synthetic"))' if failure=='network' else f'Promise.resolve(new Response("{{}}",{{status:{failure}}}))')+''';
                return logoutFetch(path,options);};return true;})()''')
            b.click(pa,'[data-action=logout]');wait(pa,'!loading')
            check('session failed logout stays closed '+failure,b.evaluate(pa,'!!sessionUser && !document.querySelector("#accountForm") && !!routeError && !!document.querySelector("[data-action=logout]")'))
            b.evaluate(pa,'window.fetch=window.logoutFetch');switch(pa);login(pa,pe)
        # A delayed /api/me request cannot restore the old owner after the explicit switch.
        route(pa,'/login')
        b.evaluate(pa,'''(()=>{state.mood='OLD_OWNER';state.draft.text='OLD_DRAFT';state.questionnaires.old={answer:1};
            state.chatDrafts.old='OLD_CHAT';window.lateFetch=fetch;window.fetch=(path,options)=>path==='/api/me'?
            lateFetch(path,options).then(r=>new Promise(resolve=>setTimeout(()=>resolve(r),500))):lateFetch(path,options);
            window.lateResult=CompassAPI.request('/api/me').catch(e=>e.name);return true;})()''')
        switch(pa);b.evaluate(pa,'window.fetch=window.lateFetch');login(pa,pbe)
        check('session late result invalidated',b.evaluate(pa,'window.lateResult')=='AbortError')
        check('session switch clears private state',b.evaluate(pa,'sessionUser.name.includes("patientb") && !state.mood && !state.draft.text && !state.reports.length && !Object.keys(state.questionnaires).length && !Object.keys(state.chatDrafts).length'))
        b.evaluate(pa,'CompassAPI.auth("auth/session",{method:"DELETE"})');route(pa,'/register/doctor')
        check('session expired shows ordinary form',b.evaluate(pa,'!sessionUser && !!document.querySelector("#profileName") && !state.reports.length'))
        login(pa,pe)
        route(pa,'/login')
        b.evaluate(pa,'''(()=>{window.publicFetch=fetch;window.fetch=(path,options)=>path==='/api/me'?
            Promise.reject(new TypeError('synthetic')):publicFetch(path,options);loadRoute();return true;})()''')
        wait(pa,'!loading')
        check('session public check failure hides unconfirmed account',b.evaluate(pa,'!!routeError && !document.body.innerText.includes("Вы уже вошли") && !document.querySelector("#accountForm")'))
        b.evaluate(pa,'window.fetch=window.publicFetch');b.click(pa,'[data-api-retry]');wait(pa,'!loading')
        check('session public check retry confirms account',current(pa))
        # Key/password routes remain independent even with a valid session.
        for path,mode in [('/verify-email/invalid','verify'),('/password/reset/invalid','reset'),('/password/request','request'),('/password/change','change')]:
            route(pa,path);check('session separate account flow '+mode,b.evaluate(pa,'document.querySelector("#accountForm")?.dataset.mode')==mode)
            if mode in ['verify','reset']:
                if mode=='reset':fill(pa,{'password':password+'new','password_repeat':password+'new'})
                submit(pa);wait(pa,'!authBusy')
                check('session real invalid link '+mode,b.evaluate(pa,'!!authError && !authNotice && !!document.querySelector("#accountForm")'))
        # Real invalid credentials and injected safe server shapes for both normal forms.
        cases=[(400,{'errors':[{'message':'Проверьте введённые данные.','code':'invalid'}]},'Проверьте'),
            (400,{'error':{'code':'invalid','message':'Исправьте поля формы.'}},'Исправьте'),
            (403,{'status':200,'meta':{'is_authenticated':True},'error':{'code':'csrf','message':'Недопустимый запрос.'}},'Обновите'),
            (429,{},'Слишком много'),(503,{},'временно недоступ'),(418,{},'Не удалось'),(200,{},'Не удалось')]
        for path in ['/login','/register/doctor']:
            route(anonymous,path)
            for status,body,expected in cases+[(0,{},'соединение')]:
                values={'accountEmail':pe,'password':password}
                if path!='/login':values.update(profileName='Учебное имя',password_repeat=password)
                fill(anonymous,values)
                response='Promise.reject(new TypeError("synthetic transport details"))' if status==0 else 'Promise.resolve(new Response('+json.dumps(json.dumps(body,ensure_ascii=False))+',{status:'+str(status)+'}))'
                b.evaluate(anonymous,'''(()=>{window.errorFetch=fetch;window.fetch=(path,options)=>options?.method==='POST'?'''+response+''':errorFetch(path,options);return true;})()''')
                submit(anonymous);wait(anonymous,'!authBusy && !loading')
                check(f'session safe error {path} {status} {expected}',b.evaluate(anonymous,'!!authError && !sessionUser && !authNotice && !authError.includes("Ссылка") && !authError.includes("synthetic") && authError.includes('+json.dumps(expected)+')'))
                b.evaluate(anonymous,'window.fetch=window.errorFetch')
        route(anonymous,'/login');fill(anonymous,{'accountEmail':pe,'password':password+'wrong'});submit(anonymous);wait(anonymous,'!authBusy')
        check('session real invalid credentials',b.evaluate(anonymous,'!!authError && !sessionUser && !authError.includes("Ссылка")'))
        for path in ['/verify-email/invalid','/password/reset/invalid']:
            route(anonymous,path)
            if 'password/reset' in path:fill(anonymous,{'password':password+'new','password_repeat':password+'new'})
            submit(anonymous);wait(anonymous,'!authBusy')
            check('session anonymous invalid link '+path,b.evaluate(anonymous,'!!authError && !authNotice'))
            route(anonymous,'/login')
            check('session link error does not carry into login '+path,b.evaluate(anonymous,'!authError && !sessionUser && !!document.querySelector("#accountForm") && !document.body.innerText.includes("Ссылка")'))
        # A late auth response after navigation must not move the user to a cabinet.
        fill(anonymous,{'accountEmail':pe,'password':password})
        b.evaluate(anonymous,'''(()=>{window.authLateFetch=fetch;window.fetch=(path,options)=>path.endsWith('/auth/login')?
            authLateFetch(path,options).then(r=>new Promise(resolve=>setTimeout(()=>resolve(r),600))):authLateFetch(path,options);return true;})()''')
        submit(anonymous);route(anonymous,'/password/request');time.sleep(.8);wait(anonymous,'!loading')
        check('session late auth does not navigate',b.evaluate(anonymous,'readRoute().view==="password-request" && !authBusy && !authError'))
        b.evaluate(anonymous,'window.fetch=window.authLateFetch')
        route(pa,'/patient');route(da,'/doctor')
        print('Session recovery, switching, errors and delayed responses passed',flush=True)
    try:
        c=b.context(private=True);b.navigate(c,base+'/#/doctor');wait(c,'!loading')
        check('direct protected hash requires login',b.evaluate(c,'!!document.querySelector("#accountForm") && !sessionUser'))
        pa,pe=create('patient','patienta');pb,pbe=create('patient','patientb');da,de=create('doctor','doctora');db,dbe=create('doctor','doctorb')
        check('doctor pending after signup',b.evaluate(da,'document.body.innerText.includes("Заявка ожидает одобрения")'))
        for path in ['/','/login','/register/patient','/register/doctor']:
            route(da,path)
            check('session pending doctor '+path,b.evaluate(da,'!!sessionUser && !sessionUser.doctor_approved && document.body.innerText.includes("Вы уже вошли") && document.body.innerText.includes("Врач") && !document.querySelector("#accountForm")'))
        route(da,'/doctor')
        operator('doctor_access','approve',de);operator('doctor_access','approve',dbe)
        operator('care_relationship','assign',pe,de);operator('care_relationship','assign',pbe,dbe)
        for x in [da,db]:b.evaluate(x,'loadRoute()');wait(x,'!loading')
        check('only own linked patient listed',b.evaluate(da,'people.length===1 && people[0].name.includes("patienta")'))
        if args.project in {'veganmedtech-work0018-test','veganmedtech-work0020-test'}:
            navigation_checks(pa,pe,pb,pbe,da)
            if args.navigation_only:
                Path(args.output).write_text(json.dumps({'passed':len(results),'failed':0,'checks':results},ensure_ascii=False,indent=2)+'\n')
                return
        session_checks(pa,pe,pb,pbe,da,de)
        route(pa,'/patient/report')
        text='SYNTHETIC_BROWSER_REPORT_0008 <img src=x onerror="window.injected=true">'
        fill(pa,{'reportText':text});submit(pa,'#reportForm button[type=submit]')
        wait(pa,'readRoute().view === "history" && !loading')
        check('patient persisted report safe text',b.evaluate(pa,'document.body.innerText.includes("SYNTHETIC_BROWSER_REPORT_0008") && !window.injected && !document.querySelector("img[src=x]")'))
        patient_id=b.evaluate(pa,'sessionUser.id')
        route(da,f'/doctor/patients/{patient_id}')
        check('independent doctor sees saved report',b.evaluate(da,'document.body.innerText.includes("SYNTHETIC_BROWSER_REPORT_0008")'))
        route(db,f'/doctor/patients/{patient_id}')
        check('foreign doctor denied and clears data',b.evaluate(db,'!!routeError && state.reports.length===0'))
        b.navigate(pa,base+'/#/patient/history');wait(pa,'!loading')
        check('report survives reload',b.evaluate(pa,'state.reports.length===1'))
        route(pb,'/patient/history');check('other patient empty history',b.evaluate(pb,'state.reports.length===0'))
        # Server-side rejections are also visible to a real browser session.
        check('server validation from browser',b.evaluate(pa,'(async()=>{try{await CompassAPI.request("/api/me/self-reports",{method:"POST",body:{observed_at:"bad",text:""},headers:{"Idempotency-Key":"browser-invalid"}});return false;}catch(e){return e.status===400;}})()'))
        route(pa,'/patient/report')
        fill(pa,{'reportText':'Черновик при сетевой ошибке'})
        b.evaluate(pa,'(()=>{window.originalFetch=window.fetch;window.fetch=(...args)=>String(args[0]).endsWith("/api/me/self-reports")&&args[1]?.method==="POST"?originalFetch(...args).then(()=>{throw new TypeError("synthetic lost response")}):originalFetch(...args);return true;})()')
        submit(pa,'#reportForm button[type=submit]');wait(pa,'!state.pending')
        check('failed write keeps draft',b.evaluate(pa,'state.saveError && state.draft.text.includes("Черновик")'))
        b.evaluate(pa,'window.fetch=window.originalFetch')
        submit(pa,'#reportForm button[type=submit]');wait(pa,'readRoute().view==="history" && !loading')
        check('retry succeeds once',b.evaluate(pa,'state.reports.length===2'))
        # Layout and retained local features, in each required width.
        patient_routes=['/patient','/patient/assistant','/patient/questionnaires','/patient/notifications','/patient/doctors','/patient/chat/doctor-a','/patient/medication','/patient/games','/patient/films','/patient/sounds','/patient/report','/patient/history']
        for width in [1440,768,390]:
            b.viewport(pa,width)
            for path in patient_routes:
                route(pa,path)
                check(f'layout {width} {path}',b.evaluate(pa,'!!document.querySelector("#pageTitle") && document.documentElement.scrollWidth <= innerWidth+1 && !routeError'))
            for tool in ['lsia','bipq','temmo','stolin']:
                route(pa,'/patient/questionnaires/'+tool)
                b.evaluate(pa,'document.querySelector("[data-q-action=start]")?.click()')
                layouts=b.evaluate(pa,'(()=>{const tool=CompassQuestionnaires.get('+json.dumps(tool)+');const draft=qDraft(tool);return tool.questions.map((q,step)=>{draft.step=step;render();return !!document.querySelector("#questionnaireForm") && document.documentElement.scrollWidth<=innerWidth+1;});})()')
                check(f'questionnaire {width} {tool}',all(layouts))
            b.viewport(da,width)
            for path in ['/doctor',f'/doctor/patients/{patient_id}','/doctor/interactions']:
                route(da,path)
                check(f'doctor layout {width} {path}',b.evaluate(da,'!!document.querySelector("#pageTitle") && document.documentElement.scrollWidth <= innerWidth+1 && !routeError'))
        route(pa,'/patient/games');b.evaluate(pa,'document.querySelector("[data-action=breath-toggle]").click()')
        check('breathing starts',b.evaluate(pa,'state.breathRunning'))
        route(pa,'/patient/films');check('leaving stops breathing',b.evaluate(pa,'!state.breathRunning && !breathTimer'))
        route(pa,'/patient/sounds');b.click(pa,'[data-action=audio-toggle]');wait(pa,'state.audioStatus !== "loading"')
        check('sound starts or reports supported error',b.evaluate(pa,'state.audioStatus==="playing" || !!state.audioError'))
        if b.evaluate(pa,'state.audioStatus === "playing"'):
            b.click(pa,'[data-action=audio-toggle]');wait(pa,'state.audioStatus !== "loading"');check('sound pauses',b.evaluate(pa,'state.audioStatus==="paused"'))
        route(pa,'/patient/films');check('leaving closes audio',b.evaluate(pa,'audio===null'))
        route(pa,'/patient/chat/doctor-a');fill(pa,{'chatText':'Локальное учебное сообщение'});submit(pa,'#chatForm button[type=submit]');wait(pa,'!state.chatPending')
        check('local chat labelled and does not reassign doctor',b.evaluate(pa,'state.messages["patient-a:doctor-a"].length===2 && sessionUser.leading_doctor.name.includes("doctora")'))
        route(pa,'/patient/medication');check('calendar renders controls',b.evaluate(pa,'document.querySelectorAll("[data-day]").length>=28'))
        # Keyboard and computed contrast for representative actionable text.
        route(pa,'/patient/report')
        b.call('input.performActions',{'context':pa,'actions':[{'type':'key','id':'keyboard','actions':[{'type':'keyDown','value':'\ue004'},{'type':'keyUp','value':'\ue004'}]}]})
        check('keyboard focus visible target',b.evaluate(pa,'document.activeElement!==document.body'))
        contrast=b.evaluate(pa,'''(()=>{function rgb(s){return s.match(/[0-9.]+/g).slice(0,3).map(Number)}function lum(c){return c.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0)}const selectors=['body','.btn','.retention','.field-help'];return selectors.map(selector=>{const el=document.querySelector(selector),s=getComputedStyle(el);let p=el,bg=s.backgroundColor;while(bg==='rgba(0, 0, 0, 0)'&&p.parentElement){p=p.parentElement;bg=getComputedStyle(p).backgroundColor}const a=lum(rgb(s.color)),b=lum(rgb(bg));return {selector,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)}})})()''')
        check('representative contrast >= 4.5',all(x['ratio']>=4.5 for x in contrast))
        # Revoke while a doctor holds an old session and a loaded card.
        route(da,f'/doctor/patients/{patient_id}');operator('care_relationship','revoke',pe)
        b.evaluate(da,'loadRoute()');wait(da,'!loading')
        check('revoked relationship clears card',b.evaluate(da,'!!routeError && state.reports.length===0 && !document.body.innerText.includes("SYNTHETIC_BROWSER_REPORT_0008")'))
        # Logout clears local answers, chat, drafts and ignores an old delayed API result.
        route(pa,'/patient/questionnaires/lsia');b.evaluate(pa,'document.querySelector("[data-q-action=start]")?.click()')
        b.evaluate(pa,'(()=>{window.originalFetch=fetch;window.fetch=(path,options)=>path==="/api/me"?originalFetch(path,options).then(response=>new Promise(resolve=>setTimeout(()=>resolve(response),700))):originalFetch(path,options);window.delayed=CompassAPI.request("/api/me").catch(()=>null);state.mood="Локальное настроение";return true;})()')
        b.evaluate(pa,'logout()');wait(pa,'!loading && !sessionUser');b.evaluate(pa,'window.fetch=window.originalFetch');b.evaluate(pa,'window.delayed')
        check('logout clears local personal state',b.evaluate(pa,'!state.mood && Object.keys(state.questionnaires).length===0 && !state.draft.text && state.reports.length===0 && state.messages["patient-a:doctor-a"].length===1'))
        route(pa,'/login');fill(pa,{'accountEmail':pbe,'password':password});submit(pa);wait(pa,'!!sessionUser && !loading && readRoute().view!=="login"')
        check('second user in same tab sees no previous data',b.evaluate(pa,'sessionUser.name.includes("patientb") && state.reports.length===0 && !state.mood'))
        # Password request email and reset through the UI.
        b.evaluate(pa,'logout()');wait(pa,'!loading && !sessionUser');route(pa,'/password/request')
        fill(pa,{'accountEmail':pbe});submit(pa);wait(pa,'!authBusy');check('password request UI',bool(b.evaluate(pa,'authNotice')))
        url=mail_link(pbe,'password/reset');b.navigate(pa,url);wait(pa,'!loading')
        fill(pa,{'password':password+'NEW','password_repeat':password+'NEW'});submit(pa);wait(pa,'!authBusy')
        check('password reset UI',not b.evaluate(pa,'authError'))
        # Static integrity calculation page remains local, never HTTP published.
        calc=b.context(private=True);b.navigate(calc,(ROOT/'frontend/tests/questionnaires.html').as_uri());wait(calc,'typeof testResults !== "undefined"')
        calculation=b.evaluate(calc,'({passed:testResults.passed,failed:testResults.failed})')
        check('219 calculation regressions',calculation=={'passed':219,'failed':0})
        report={'passed':sum(x['passed'] for x in results),'failed':sum(not x['passed'] for x in results),'checks':results,'contrast':contrast,'calculations':calculation}
        Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'passed':report['passed'],'failed':report['failed'],'calculations':calculation},ensure_ascii=False))
    except Exception:
        Path(args.output).write_text(json.dumps({'passed':sum(x['passed'] for x in results),'failed':max(1,sum(not x['passed'] for x in results)),'checks':results},ensure_ascii=False,indent=2)+'\n')
        raise
    finally:
        b.close()

if __name__=='__main__':main()
