"""WORK-0018: reduced motion and late assistant responses, synthetic local data only."""
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'tests/browser'))
from bidi import Browser

OUTPUT = Path(__file__).resolve().parent
compose = ['docker', 'compose', '--env-file', '/tmp/work0018-test.env', '-p', 'veganmedtech-work0018-test']
password = secrets.token_urlsafe(24)
suffix = secrets.token_hex(6)
emails = {role: role + '-motion-' + suffix + '@example.test' for role in ['patient', 'doctor']}


def operator(code):
    subprocess.run(compose + ['exec', '-T', 'app', 'python', 'manage.py', 'shell', '-c', code], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)


for role, email in emails.items():
    operator('from accounts.models import User;from allauth.account.models import EmailAddress;'
             'u=User.objects.create_user(email=' + repr(email) + ',password=' + repr(password) + ',display_name="Учебная проверка",role=' + repr(role) + ',doctor_approved=' + repr(role == 'doctor') + ');'
             'EmailAddress.objects.create(user=u,email=u.email,verified=True,primary=True)')

b = Browser(19229)
checks = []


def check(name, value):
    checks.append({'name': name, 'passed': bool(value)})
    if not value:
        raise AssertionError(name)


def route(c, path):
    b.evaluate(c, 'location.hash=' + json.dumps(path))
    time.sleep(.15)
    b.wait(c, '!loading')


try:
    for role, email in emails.items():
        c = b.context(private=True)
        b.navigate(c, 'http://localhost:18018/#/login');b.wait(c, '!loading')
        b.evaluate(c, '(()=>{document.querySelector("#accountEmail").value=' + json.dumps(email) + ';document.querySelector("#password").value=' + json.dumps(password) + ';document.querySelector("#accountForm button").click();return true;})()')
        b.wait(c, '!!sessionUser && !loading && readRoute().view!=="login"')
        check('reduced motion active ' + role, b.evaluate(c, 'matchMedia("(prefers-reduced-motion: reduce)").matches'))
        for width in [1440, 768, 390]:
            b.viewport(c, width)
            route(c, '/patient/games' if role == 'patient' else '/doctor')
            check(f'reduced screen animation {role} {width}', b.evaluate(c, 'getComputedStyle(document.querySelector(".screen-enter")).animationName==="none"'))
            if role == 'patient':
                check(f'reduced breathing animation {width}', b.evaluate(c, 'getComputedStyle(document.querySelector(".breath-dot")).animationName==="none"'))
                route(c, '/patient/report')
                b.evaluate(c, 'document.querySelector("#reportText").value="Учебный черновик"')
            b.evaluate(c, '''(()=>{window.savedFetch=fetch;window.pendingMain=document.querySelector('#mainContent');window.pendingWrites=0;window.finishNavigation=null;
                window.fetch=(path,options)=>{if(options?.method && options.method!=='GET')pendingWrites++;
                    return savedFetch(path,options).then(response=>path==='/api/me'?new Promise(resolve=>window.finishNavigation=()=>resolve(response)):response);};return true;})()''')
            target = '/patient/films' if role == 'patient' else '/doctor/interactions'
            b.evaluate(c, '(()=>{location.hash=' + json.dumps(target) + ';document.querySelector("#reportForm")?.requestSubmit();return true;})()')
            b.wait(c, '!!finishNavigation')
            check(f'reduced transition retains view {role} {width}', b.evaluate(c, 'pendingMain===document.querySelector("#mainContent") && pendingMain.inert && !!document.querySelector("#routeStatus") && !document.body.innerText.includes("Загружаем…")'))
            check(f'old form blocked before hashchange {role} {width}', b.evaluate(c, 'pendingWrites===0'))
            b.evaluate(c, 'finishNavigation()');b.wait(c, '!loading')
            check(f'reduced ready layout and focus {role} {width}', b.evaluate(c, 'document.activeElement===document.querySelector("#pageTitle") && !document.querySelector("#routeStatus") && document.documentElement.scrollWidth<=innerWidth+1'))
            b.evaluate(c, 'window.fetch=savedFetch')
            if width == 390:
                b.screenshot(c, OUTPUT / (role + '-ready-390.png'))
        if role == 'patient':
            route(c, '/patient/assistant')
            b.evaluate(c, '''(()=>{window.pollFetch=fetch;window.finishPoll=null;window.finishNavigation=null;
                window.pendingMain=document.querySelector('#mainContent');
                window.fetch=(path,options)=>path==='/api/me/assistant/messages/999999'?new Promise(resolve=>window.finishPoll=()=>resolve(new Response('{}',{status:401}))):
                    pollFetch(path,options).then(response=>path==='/api/me'?new Promise(resolve=>window.finishNavigation=()=>resolve(response)):response);
                state.assistant.items=[{id:999999,status:'pending'}];scheduleAssistantPolling();return true;})()''')
            b.wait(c, '!!finishPoll')
            b.evaluate(c, 'location.hash="/patient/films"');b.wait(c, '!!finishNavigation')
            b.evaluate(c, 'finishPoll()');time.sleep(.15)
            check('late assistant poll cannot clear session or replace pending view', b.evaluate(c, 'loading && !!sessionUser && pendingMain===document.querySelector("#mainContent") && !state.assistant.error'))
            b.evaluate(c, 'finishNavigation()');b.wait(c, '!loading');b.evaluate(c, 'window.fetch=pollFetch')
            route(c, '/patient/assistant')
            b.evaluate(c, '''(()=>{window.sendFetch=fetch;window.finishSend=null;
                window.fetch=(path,options)=>path==='/api/me/assistant/messages'&&options?.method==='POST'?
                    new Promise(resolve=>window.finishSend=()=>resolve(new Response('{}',{status:401}))):sendFetch(path,options);
                state.assistant.draft='Учебное сообщение';sendAssistant();return true;})()''')
            b.wait(c, '!!finishSend');route(c, '/patient/films')
            b.evaluate(c, 'finishSend()');time.sleep(.15)
            check('late assistant send cannot clear session after navigation', b.evaluate(c, '!!sessionUser && !routeError && document.title.startsWith("Кино") && !state.assistant.error'))
            b.evaluate(c, 'window.fetch=sendFetch')
    print(json.dumps({'passed': len(checks), 'failed': 0}))
finally:
    (OUTPUT / 'accessibility.json').write_text(json.dumps({'passed': sum(x['passed'] for x in checks), 'failed': sum(not x['passed'] for x in checks), 'checks': checks}, ensure_ascii=False, indent=2) + '\n')
    b.close()
    operator('from accounts.models import User;User.objects.filter(email__in=' + repr(list(emails.values())) + ').update(is_active=False)')
