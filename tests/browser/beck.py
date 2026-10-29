"""WORK-0023: real Firefox UI, isolated mock account API; no database or external calls.

Run: python3 tests/browser/beck.py --output /tmp/compass-beck-browser
Only synthetic identities/answers. This is not server authorization acceptance.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import threading
import time
from bidi import Browser

ROOT = Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('/tmp/compass-beck-browser'))
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    checks=[];traffic=[]
    def check(name,condition):
        checks.append({'name':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,data,status=200,kind='application/json'):
            body=json.dumps(data,ensure_ascii=False).encode() if kind=='application/json' else data
            self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
        def do_GET(self):
            traffic.append({'method':'GET','path':self.path})
            if self.path=='/api/me':
                if self.server.user:self.reply({'id':self.server.user,'name':'Вымышленный пациент','initials':'ВП','role':'patient'})
                else:self.reply({'error':{'message':'Войдите в аккаунт'}},401)
            elif self.path=='/api/questionnaires/module':
                if self.server.user:self.reply((ROOT/'frontend/static/js/questionnaires.js').read_bytes(),kind='application/javascript')
                else:self.reply({},401)
            elif self.path=='/api/me/self-reports':self.reply({'results':[],'next_cursor':None})
            elif self.path=='/calculations.html':
                html=(ROOT/'frontend/tests/questionnaires.html').read_text().replace('../static/js/questionnaires.js','/api/questionnaires/module')
                self.reply(html.encode(),kind='text/html')
            elif self.path=='/':
                html=(ROOT/'frontend/templates/index.html').read_text().replace('{% load static %}','')
                html=re.sub(r"\{% static '([^']+)' %\}",r'/static/\1',html)
                self.reply(html.encode(),kind='text/html')
            elif self.path in ['/static/js/api.js','/static/js/app.js','/static/css/app.css']:
                self.reply((ROOT/'frontend'/self.path.lstrip('/')).read_bytes(),kind='text/css' if self.path.endswith('.css') else 'application/javascript')
            else:self.reply({},404)
        def do_DELETE(self):
            traffic.append({'method':'DELETE','path':self.path})
            if self.path=='/_allauth/browser/v1/auth/session':self.server.user=None;self.reply({})
            else:self.reply({},404)
        def do_POST(self):traffic.append({'method':'POST','path':self.path});self.reply({},405)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.user=1
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base='http://127.0.0.1:'+str(server.server_port)
    with socket.socket() as port_socket:port_socket.bind(('127.0.0.1',0));port=port_socket.getsockname()[1]
    profile=tempfile.TemporaryDirectory(prefix='compass-beck-firefox-')
    log=(args.output/'firefox.txt').open('w')
    process=subprocess.Popen(['firefox','--headless','--no-remote','--remote-debugging-port',str(port),'--profile',profile.name],stdout=log,stderr=subprocess.STDOUT)
    browser=None
    try:
        for _ in range(120):
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.1):break
            except OSError:
                if process.poll() is not None:raise RuntimeError('Firefox exited; see firefox.txt')
                time.sleep(.1)
        browser=Browser(port,accept_insecure=False)
        for width in [1440,390]:
            server.user=1;c=browser.context(private=True);browser.viewport(c,width)
            def evaluate(expression):return browser.evaluate(c,expression)
            def click(selector):
                time.sleep(.08)  # Let the form focus timer settle before pointer geometry.
                browser.click(c,selector)
            def wait(expression):browser.wait(c,expression)
            def submit():evaluate('document.querySelector("#questionnaireForm").requestSubmit()')
            def choose(index):evaluate(f'document.querySelectorAll("[name=qAnswer]")[{index}].click()')
            def screenshot(path):
                evaluate('(async()=>{document.activeElement?.blur();window.scrollTo(0,0);await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return true;})()')
                time.sleep(.35)
                browser.screenshot(c,path)
            def key(value):browser.call('input.performActions',{'context':c,'actions':[{'type':'key','id':'keyboard','actions':[{'type':'keyDown','value':value},{'type':'keyUp','value':value}]}]})
            browser.navigate(c,base+'/#/patient/questionnaires')
            wait('document.querySelectorAll(".q-card").length===5')
            check(f'{width}: catalog 5 and BDI metadata',evaluate('document.querySelector(".q-card:last-child").textContent.includes("Четыре варианта")'))
            click('a[href="#/patient/questionnaires/bdi"]');wait('!!document.querySelector(".q-start")')
            check(f'{width}: source and edition before start',evaluate('document.querySelector(".q-aside").textContent.includes("BDI-IA")'))
            click('[data-q-action=start]');wait('!!document.querySelector("[data-q-answer]")')
            check(f'{width}: no default answer',evaluate('document.querySelectorAll("[name=qAnswer]:checked").length===0'))
            submit();wait('!document.querySelector("#qError").hidden && document.activeElement.matches("[name=qAnswer]")')
            check(f'{width}: required answer error',evaluate('!state.questionnaires.bdi.result && state.questionnaires.bdi.step===0'))
            key(' ');key('\ue004')
            check(f'{width}: keyboard radio and tab to submit',evaluate('document.querySelector("[name=qAnswer]:checked").value==="0" && document.activeElement.type==="submit"'))
            key('\ue007');wait('state.questionnaires.bdi.step===1')
            click('[data-q-action=back]');wait('state.questionnaires.bdi.step===0')
            check(f'{width}: back preserves zero',evaluate('document.querySelector("[name=qAnswer]:checked").value==="0" && document.querySelector("#qProgress").value===1'))
            submit()
            for i in range(1,21):
                data=evaluate('({step:state.questionnaires.bdi.step,question:document.querySelector("#qQuestion").textContent,labels:[...document.querySelectorAll(".q-option>span")].map(x=>x.textContent),selected:document.querySelectorAll("[name=qAnswer]:checked").length,expected:CompassQuestionnaires.get("bdi").questions[state.questionnaires.bdi.step],options:CompassQuestionnaires.getOptions("bdi",state.questionnaires.bdi.step).map(x=>x[1]),overflow:document.documentElement.scrollWidth>innerWidth+1})')
                check(f'{width}: group {i+1}, own four options, no default, fits',data['step']==i and data['question']==data['expected'] and data['labels']==data['options'] and len(data['labels'])==4 and data['selected']==0 and not data['overflow'])
                if i==19:screenshot(args.output/f'bdi-question-{width}.png')
                choose(i%4);submit()
            wait('!!document.querySelector(".q-result-hero")')
            check(f'{width}: result 30, two subscales, edition',evaluate('state.questionnaires.bdi.result.total===30 && JSON.stringify(state.questionnaires.bdi.result.groups.map(x=>x.raw))==="[18,12]" && document.querySelector(".q-result-note").textContent.includes("BDI-IA")'))
            screenshot(args.output/f'bdi-result-{width}.png')
            click('[data-q-action=edit]');wait('state.questionnaires.bdi.step===0 && !state.questionnaires.bdi.showResult')
            choose(3);check(f'{width}: changing answer invalidates old result',evaluate('state.questionnaires.bdi.result===null'))
            for i in range(21):submit()
            wait('!!document.querySelector(".q-result-hero")')
            check(f'{width}: recompute to 33',evaluate('state.questionnaires.bdi.result.total===33'))
            click('[data-q-action=reset-prompt]');click('[data-q-action=reset-cancel]')
            check(f'{width}: reset cancelled',evaluate('state.questionnaires.bdi.result.total===33'))
            click('[data-q-action=reset-prompt]');click('[data-q-action=reset-confirm]')
            wait('!!document.querySelector("#qProgress")')
            check(f'{width}: explicit reset clears answers',evaluate('state.questionnaires.bdi.answers.every(x=>x===null) && !state.questionnaires.bdi.result && document.querySelector("#qProgress").value===0'))
            choose(2);evaluate('location.hash="/patient/questionnaires"');wait('document.querySelectorAll(".q-card").length===5')
            click('a[href="#/patient/questionnaires/bdi"]');wait('!!document.querySelector("[name=qAnswer]:checked")')
            check(f'{width}: draft resumed',evaluate('document.querySelector("[name=qAnswer]:checked").value==="2"'))
            server.user=2;evaluate('location.hash="/patient/questionnaires"');wait('sessionUser.id===2 && document.querySelectorAll(".q-card").length===5')
            check(f'{width}: account switch clears local answers',evaluate('Object.keys(state.questionnaires).length===0'))
            click('a[href="#/patient/questionnaires/bdi"]');wait('!!document.querySelector(".q-start")');click('[data-q-action=start]');choose(1)
            if width==390:evaluate('document.querySelector(".mobile-menu").open=true')
            click(('.mobile-menu ' if width==390 else '.sidebar ')+'[data-action=logout]')
            wait('sessionUser===null && !!document.querySelector("#accountForm")')
            check(f'{width}: logout clears all drafts',evaluate('Object.keys(state.questionnaires).length===0'))
            server.user=1;evaluate('location.hash="/patient/questionnaires/bdi"');wait('!!document.querySelector(".q-start")')
            check(f'{width}: re-entry is empty',evaluate('state.questionnaires.bdi.answers.every(x=>x===null)'))
            for tool,count,total in [('lsia',20,20),('bipq',8,30),('temmo',36,66),('stolin',57,None)]:
                evaluate('location.hash='+json.dumps('/patient/questionnaires/'+tool));wait('!!document.querySelector(".q-start")');click('[data-q-action=start]')
                for i in range(count):choose(0);submit()
                if tool=='bipq':submit()
                wait('!!document.querySelector(".q-result-hero")')
                result=evaluate('state.questionnaires['+json.dumps(tool)+'].result')
                check(f'{width}: previous {tool} completes',result.get('total')==total if total is not None else len(result['groups'])==12)
            check(f'{width}: storage empty',evaluate('localStorage.length===0 && sessionStorage.length===0'))
        calc=browser.context(private=True);browser.navigate(calc,base+'/calculations.html')
        browser.wait(calc,'!!window.testResults')
        calculations=browser.evaluate(calc,'window.testResults')
        check('Firefox: 250 calculations',calculations['passed']==250 and calculations['failed']==0)
        check('No answer POST/PUT requests',all(r['method'] in ['GET','DELETE'] for r in traffic))
        (args.output/'calculations.json').write_text(json.dumps(calculations,ensure_ascii=False,indent=2)+'\n')
    finally:
        (args.output/'browser.json').write_text(json.dumps({'environment':'Real Firefox, loopback fixture with mock /api/me and logout; no database/server permission acceptance','checks':checks,'traffic':traffic},ensure_ascii=False,indent=2)+'\n')
        if browser:browser.close()
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        log.close();profile.cleanup();server.shutdown();server.server_close()
    print(json.dumps({'passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks),'output':str(args.output)},ensure_ascii=False))

if __name__=='__main__':main()
