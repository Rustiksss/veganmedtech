"""Real Firefox + real local API on an isolated synthetic database.

Run only against the dedicated fixture server from WORK-0025.
python3 tests/browser/prescriptions.py --base http://127.0.0.1:18025 --output /tmp/work25-browser
"""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from bidi import Browser


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:18025')
    parser.add_argument('--output', type=Path, default=Path('/tmp/work25-browser'))
    args = parser.parse_args()
    if not args.base.startswith('http://127.0.0.1:'):
        raise SystemExit('Dedicated local fixture server required')
    args.output.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})
        if not condition: raise AssertionError(name)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    profile = tempfile.TemporaryDirectory(prefix='compass-prescriptions-firefox-')
    log = (args.output/'firefox.txt').open('w')
    process = subprocess.Popen(['firefox','--headless','--no-remote','--remote-debugging-port',str(port),'--profile',profile.name], stdout=log, stderr=subprocess.STDOUT)
    browser = None
    try:
        for _ in range(120):
            try:
                with socket.create_connection(('127.0.0.1',port), timeout=.1): break
            except OSError: time.sleep(.1)
        browser = Browser(port, accept_insecure=False)
        def route(c, path):
            browser.evaluate(c, 'location.hash='+json.dumps(path));time.sleep(.2);browser.wait(c,'!loading')
        def fill(c, fields):
            browser.evaluate(c,'(()=>{for(const [id,value] of Object.entries('+json.dumps(fields)+')){const e=document.getElementById(id);e.value=value;e.dispatchEvent(new Event("input",{bubbles:true}));}return true;})()')
        def click(c, selector):
            time.sleep(.1);browser.click(c,selector)
        def login(c, role, suffix='a'):
            browser.navigate(c,args.base+'/#/login');browser.wait(c,'!loading && !!document.querySelector("#accountEmail")')
            fill(c, {'accountEmail':role+'-'+suffix+'@example.test','password':'Synthetic-test-passphrase!42'})
            click(c,'#accountForm button[type=submit]')
            browser.wait(c,'!loading && sessionUser?.role==='+json.dumps(role)+' && location.hash==='+json.dumps('#/'+role))
        for width in [1440,390]:
            d=browser.context(private=True);p=browser.context(private=True)
            browser.viewport(d,width);browser.viewport(p,width)
            login(d,'doctor');route(d,'/doctor/patients/1')
            check(f'{width} doctor form + 11 drugs',browser.evaluate(d,'document.querySelectorAll("#prescriptionDrug option").length===12 && state.prescriptions.catalog[0].name==="Авиандр"'))
            before=browser.evaluate(d,'state.prescriptions.items.length')
            if not before:check(f'{width} empty state',browser.evaluate(d,'document.body.textContent.includes("Демоназначений пока нет")'))
            browser.call('browsingContext.activate', {'context':d})
            time.sleep(.2)
            browser.evaluate(d,'document.querySelector("#prescriptionDrug").focus()')
            browser.call('input.performActions',{'context':d,'actions':[{'type':'key','id':'keyboard','actions':[{'type':'keyDown','value':'\ue004'},{'type':'keyUp','value':'\ue004'}]}]})
            check(f'{width} keyboard select to comment',browser.evaluate(d,'document.activeElement.id==="prescriptionNote"'))
            note=f'Вымышленное назначение {width} <img src=x onerror="window.prescriptionXss=1">'
            fill(d,{'prescriptionDrug':'aviandr','prescriptionNote':note})
            click(d,'#prescriptionForm button[type=submit]');browser.wait(d,'!!document.querySelector("#prescriptionConfirmForm") && !state.prescriptions.pending')
            check(f'{width} preview no write',browser.evaluate(d,f'state.prescriptions.items.length==={before} && state.prescriptions.preview.drug_name==="Авиандр"'))
            check(f'{width} exact preview and escaped note',browser.evaluate(d,'document.querySelector("#prescriptionConfirmForm").textContent.includes("Демо Пациент А") && !document.querySelector("#prescriptionConfirmForm img") && !window.prescriptionXss'))
            click(d,'[data-prescription-edit]');browser.wait(d,'!!document.querySelector("#prescriptionDrug")')
            check(f'{width} edit retains selection',browser.evaluate(d,'document.querySelector("#prescriptionDrug").value==="aviandr" && state.prescriptions.preview===null'))
            fill(d,{'prescriptionDrug':'ibuprofen'});click(d,'#prescriptionForm button[type=submit]');browser.wait(d,'!!state.prescriptions.preview && !state.prescriptions.pending')
            check(f'{width} changed preview',browser.evaluate(d,'state.prescriptions.preview.drug_name==="Ибупрофен"'))
            click(d,'[data-prescription-edit]');fill(d,{'prescriptionDrug':'aviandr'})
            click(d,'#prescriptionForm button[type=submit]');browser.wait(d,'!!state.prescriptions.preview && !state.prescriptions.pending')
            # Simulate loss of a successful HTTP response, then retry against real API.
            browser.evaluate(d,'(()=>{window.prescriptionFetch=window.fetch;window.prescriptionLose=true;window.fetch=async(path,options)=>{const r=await prescriptionFetch(path,options);if(prescriptionLose && path==="/api/patients/1/prescriptions" && options?.method==="POST"){prescriptionLose=false;return new Response(JSON.stringify({error:{message:"Временный сбой. Повторите попытку."}}),{status:503,headers:{"Content-Type":"application/json"}});}return r;};return true;})()')
            click(d,'#prescriptionConfirmForm button[type=submit]');browser.wait(d,'!!state.prescriptions.error && !state.prescriptions.pending')
            check(f'{width} failed response keeps retryable confirmation',browser.evaluate(d,'!!state.prescriptions.preview && !!document.querySelector("[role=alert]")'))
            click(d,'#prescriptionConfirmForm button[type=submit]');browser.wait(d,'!!state.prescriptions.message && !state.prescriptions.pending')
            browser.evaluate(d,'window.fetch=prescriptionFetch')
            check(f'{width} confirmed once',browser.evaluate(d,f'state.prescriptions.items.length==={before+1} && state.prescriptions.items[0].drug_name==="Авиандр" && !state.prescriptions.preview'))
            check(f'{width} demo labels and no overflow',browser.evaluate(d,'document.body.textContent.includes("Демоназначение") && document.documentElement.scrollWidth<=innerWidth'))
            browser.screenshot(d,args.output/f'doctor-{width}.png')
            browser.navigate(d,args.base+'/#/doctor/patients/1');browser.wait(d,'!loading && !!document.querySelector("#prescriptionForm")')
            check(f'{width} persisted doctor reload no duplicate',browser.evaluate(d,f'state.prescriptions.items.length==={before+1}'))
            login(p,'patient');route(p,'/patient/prescriptions')
            check(f'{width} patient sees persisted doctor record',browser.evaluate(p,f'state.prescriptions.items.length==={before+1} && document.body.textContent.includes("Авиандр") && document.body.textContent.includes("Демо Врач А")'))
            check(f'{width} escaped saved comment',browser.evaluate(p,'!document.querySelector("[data-prescription-id] img") && !window.prescriptionXss && document.body.textContent.includes("<img")'))
            check(f'{width} patient demo notice no overflow',browser.evaluate(p,'document.body.textContent.includes("не являются рецептом") && document.documentElement.scrollWidth<=innerWidth'))
            browser.screenshot(p,args.output/f'patient-{width}.png')
            other=browser.context(private=True);browser.viewport(other,width)
            login(other,'patient','b');route(other,'/patient/prescriptions')
            check(f'{width} other patient empty list and isolation',browser.evaluate(other,'state.prescriptions.items.length===0 && document.body.textContent.includes("Демоназначений пока нет") && !document.querySelector("[data-prescription-id]")'))
            route(d,'/doctor/patients/2')
            check(f'{width} foreign patient has no retained record',browser.evaluate(d,'!!routeError && state.prescriptions.items.length===0 && !document.querySelector("[data-prescription-id]")'))
            route(d,'/doctor/patients/1')
            if width == 390:
                click(d,'.mobile-menu summary');click(d,'.mobile-menu [data-action=logout]')
            else: click(d,'.sidebar [data-action=logout]')
            browser.wait(d,'!sessionUser && !loading')
            check(f'{width} logout clears records and draft',browser.evaluate(d,'state.prescriptions.items.length===0 && !state.prescriptions.preview && !state.prescriptions.note'))
        (args.output/'browser.json').write_text(json.dumps({'checks':checks,'passed':len(checks),'environment':'Firefox headless; real local Django API + isolated PostgreSQL; synthetic fixtures only'},ensure_ascii=False,indent=2)+'\n')
        print(f'{len(checks)} real browser checks passed (1440/390)')
    finally:
        if browser: browser.close()
        process.terminate();process.wait(timeout=10);profile.cleanup();log.close()


if __name__=='__main__':main()
