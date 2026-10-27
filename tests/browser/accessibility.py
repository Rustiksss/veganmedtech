"""Focused WORK-0008 checks; run after containers.py, in a reduced-motion Firefox.

The credentials file is the private synthetic fixture produced by containers.py.
Neither it nor browser cookies are included in output artifacts.
"""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import time
from bidi import Browser


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compose-env-file', required=True)
    parser.add_argument('--credentials-file', default='/tmp/work0008-ops-private.json')
    parser.add_argument('--base-url', default='http://localhost:18008')
    parser.add_argument('--bidi-port', type=int, default=19229)
    parser.add_argument('--output-dir', default='/tmp/work0008-accessibility')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    password = json.loads(Path(args.credentials_file).read_text())['password']
    checks = []
    browser = Browser(args.bidi_port)

    def check(name, value):
        checks.append({'name': name, 'passed': bool(value)})
        if not value:
            raise AssertionError(name)

    def route(context, path):
        browser.evaluate(context, 'location.hash=' + json.dumps(path))
        time.sleep(.15)
        browser.wait(context, '!loading')

    def fill(context, values):
        browser.evaluate(context, '(()=>{for(const [id,value] of Object.entries(' + json.dumps(values) + ')){document.getElementById(id).value=value;}return true;})()')

    def login(email):
        context = browser.context(private=True)
        browser.navigate(context, args.base_url + '/#/login')
        browser.wait(context, '!loading')
        fill(context, {'accountEmail': email, 'password': password})
        browser.evaluate(context, 'document.querySelector("#accountForm button[type=submit]").click()')
        browser.wait(context, '!!sessionUser && !loading && readRoute().view!=="login"')
        return context

    try:
        public = browser.context(private=True)
        browser.navigate(public, args.base_url + '/#/register/patient')
        browser.wait(public, '!loading')
        check('operating system reduced-motion preference active', browser.evaluate(public, 'matchMedia("(prefers-reduced-motion: reduce)").matches'))
        for width in [1440, 768, 390]:
            browser.viewport(public, width)
            for path in ['/register/patient', '/register/doctor', '/login', '/password/request', '/verify-email/invalid', '/password/reset/invalid']:
                route(public, path)
                check(f'account layout and labels {width} {path}', browser.evaluate(public, 'document.documentElement.scrollWidth<=innerWidth+1 && [...document.querySelectorAll("#accountForm input")].every(el=>!!document.querySelector(`label[for="${el.id}"]`))'))
        route(public, '/register/doctor')
        browser.screenshot(public, output / 'signup-390.png')
        patient = login('patient-b@example.test')
        for width in [1440, 768, 390]:
            browser.viewport(patient, width)
            route(patient, '/password/change')
            check(f'password-change layout and labels {width}', browser.evaluate(patient, 'document.documentElement.scrollWidth<=innerWidth+1 && document.querySelectorAll("#accountForm label").length===3'))
        route(patient, '/patient/games')
        check('breathing animation disabled', browser.evaluate(patient, 'getComputedStyle(document.querySelector(".breath-dot")).animationName==="none"'))
        check('screen and spinner animation disabled', browser.evaluate(patient, '(()=>{const el=document.createElement("span");el.className="spinner screen-enter";document.body.append(el);const ok=getComputedStyle(el).animationName==="none";el.remove();return ok;})()'))
        route(patient, '/patient/report')
        fill(patient, {'reportText': '   '})
        browser.evaluate(patient, 'document.querySelector("#reportForm button[type=submit]").click()')
        check('validation error has text and focused invalid field', browser.evaluate(patient, 'document.activeElement.id==="reportText" && document.activeElement.getAttribute("aria-invalid")==="true" && document.activeElement.getAttribute("aria-describedby").includes("textError") && !!document.querySelector("#textError").innerText'))
        # A real server 409 with the key already committed for different content.
        key = 'focused-' + secrets.token_hex(8)
        fill(patient, {'reportText': 'Черновик после конфликта'})
        browser.evaluate(patient, '(async()=>{const data={observed_at:new Date(state.draft.date).toISOString(),text:"Другой учебный текст"};await CompassAPI.request("/api/me/self-reports",{method:"POST",body:data,headers:{"Idempotency-Key":' + json.dumps(key) + '}});reportKey=' + json.dumps(key) + ';reportPayload=JSON.stringify({...data,text:document.querySelector("#reportText").value});return true;})()')
        browser.evaluate(patient, 'document.querySelector("#reportForm button[type=submit]").click()')
        browser.wait(patient, '!state.pending')
        check('real conflict preserves draft with safe text', browser.evaluate(patient, 'state.saveError && state.saveMessage.includes("Конфликт") && document.querySelector("#reportText").value==="Черновик после конфликта"'))
        browser.viewport(patient, 1440)
        route(patient, '/patient')
        browser.screenshot(patient, output / 'patient-1440.png')
        doctor = login('doctor-b@example.test')
        browser.viewport(doctor, 390)
        route(doctor, '/doctor')
        browser.screenshot(doctor, output / 'doctor-390.png')
        check('doctor mobile list present', browser.evaluate(doctor, 'people.length===1 && document.documentElement.scrollWidth<=innerWidth+1'))
        route(patient, '/patient/report')
        fill(patient, {'reportText': 'Личный черновик до завершения сессии'})
        # Invalidate this fictional account's sessions in the isolated database.
        code = ('from accounts.models import User;from django.contrib.sessions.models import Session;'
                'uid=User.objects.get(email="patient-b@example.test").pk;'
                '[s.delete() for s in Session.objects.all() if s.get_decoded().get("_auth_user_id")==str(uid)]')
        subprocess.run(['docker', 'compose', '--env-file', args.compose_env_file, '-p', 'veganmedtech-work0008-test', 'exec', '-T', 'app', 'python', 'manage.py', 'shell', '-c', code], cwd=root, check=True, stdout=subprocess.DEVNULL)
        browser.evaluate(patient, 'document.querySelector("#reportForm button[type=submit]").click()')
        browser.wait(patient, '!sessionUser && !state.pending')
        check('expired session clears data and offers login', browser.evaluate(patient, 'state.reports.length===0 && !state.draft.text && !!document.querySelector("#accountForm") && !document.body.innerText.includes("Личный черновик")'))
        route(patient, '/login')
        browser.evaluate(patient, 'history.back()')
        time.sleep(.3)
        browser.wait(patient, '!loading')
        check('browser back cannot reveal previous personal view', browser.evaluate(patient, '!sessionUser && !!document.querySelector("#accountForm") && !state.draft.text && state.reports.length===0'))
    finally:
        browser.close()
        result = {'passed': sum(c['passed'] for c in checks), 'failed': sum(not c['passed'] for c in checks), 'checks': checks}
        (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': result['passed'], 'failed': result['failed']}))


if __name__ == '__main__':
    main()
