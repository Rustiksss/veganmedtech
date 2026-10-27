"""Повтор существующего прогона WORK-0008 в отдельном проекте WORK-0009.

Нужны /tmp/work0009-config (только новый синтетический проект) и Firefox
на порту 19239. Исходный тест и код приложения не изменяются.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
source = ROOT / 'tests/browser/run.py'
sys.path.insert(0, str(source.parent))
code = source.read_text().replace('veganmedtech-work0008-test', 'veganmedtech-work0009-test')
supplement = '''        # WORK-0009: local questionnaire lifecycle and privacy regressions.
        route(pa,'/patient/questionnaires')
        check('WORK0009 catalog is exactly four existing tools',b.evaluate(pa,'CompassQuestionnaires.list.map(t=>t.id).join(",")==="lsia,bipq,temmo,stolin" && document.querySelectorAll(".q-card").length===4'))
        for tool_id in ['lsia','bipq','temmo','stolin']:
            route(pa,'/patient/questionnaires/'+tool_id)
            b.evaluate(pa,'document.querySelector("[data-q-action=start]").click()')
            check(tool_id+' starts without preset answers',b.evaluate(pa,'!document.querySelector("input[name=qAnswer]:checked")'))
            submit(pa,'#questionnaireForm button[type=submit]')
            check(tool_id+' missing answer blocks progress',b.evaluate(pa,'qDraft(CompassQuestionnaires.get(readRoute().questionnaireId)).step===0 && !document.querySelector("#qError").hidden'))
            b.evaluate(pa,'document.querySelector("input[name=qAnswer]").click()')
            submit(pa,'#questionnaireForm button[type=submit]')
            check(tool_id+' next keeps first answer',b.evaluate(pa,'qDraft(CompassQuestionnaires.get(readRoute().questionnaireId)).step===1'))
            route(pa,'/patient/questionnaires')
            route(pa,'/patient/questionnaires/'+tool_id)
            check(tool_id+' draft survives catalog navigation',b.evaluate(pa,'qDraft(CompassQuestionnaires.get(readRoute().questionnaireId)).step===1'))
            b.evaluate(pa,'(()=>{const t=CompassQuestionnaires.get(readRoute().questionnaireId),d=qDraft(t);d.answers=Array(t.questions.length).fill(t.options[0][0]);d.step=t.questions.length-1+(t.id==="bipq"?1:0);render();return true;})()')
            b.evaluate(pa,'(()=>{window.qNetwork=[];window.qOriginalFetch=fetch;window.fetch=(path,options)=>{qNetwork.push({path:String(path),body:options?.body||null});return qOriginalFetch(path,options)};return true;})()')
            submit(pa,'#questionnaireForm button[type=submit]')
            check(tool_id+' complete answers produce result',b.evaluate(pa,'!!qDraft(CompassQuestionnaires.get(readRoute().questionnaireId)).result && !!document.querySelector(".q-result-hero")'))
            b.evaluate(pa,'document.querySelector("[data-q-action=edit]").click()')
            b.evaluate(pa,'document.querySelectorAll("input[name=qAnswer]")[1].click()')
            check(tool_id+' editing invalidates old result',b.evaluate(pa,'!qDraft(CompassQuestionnaires.get(readRoute().questionnaireId)).result'))
            b.evaluate(pa,'(()=>{const t=CompassQuestionnaires.get(readRoute().questionnaireId);qDraft(t).step=t.questions.length-1+(t.id==="bipq"?1:0);render();return true;})()')
            submit(pa,'#questionnaireForm button[type=submit]')
            check(tool_id+' recalculation succeeds',b.evaluate(pa,'!!qDraft(CompassQuestionnaires.get(readRoute().questionnaireId)).result'))
            b.evaluate(pa,'document.querySelector("[data-q-action=reset-prompt]").click()')
            b.evaluate(pa,'document.querySelector("[data-q-action=reset-cancel]").click()')
            check(tool_id+' cancelling reset keeps result',b.evaluate(pa,'!!qDraft(CompassQuestionnaires.get(readRoute().questionnaireId)).result'))
            b.evaluate(pa,'document.querySelector("[data-q-action=reset-prompt]").click()')
            b.evaluate(pa,'document.querySelector("[data-q-action=reset-confirm]").click()')
            check(tool_id+' explicit reset clears answers',b.evaluate(pa,'(()=>{const t=CompassQuestionnaires.get(readRoute().questionnaireId),d=qDraft(t);return d.answers.every(x=>x===null)&&d.step===0&&!d.result;})()'))
            check(tool_id+' local lifecycle sends no requests',b.evaluate(pa,'qNetwork.length===0'))
            check(tool_id+' answers absent from URL and storage',b.evaluate(pa,'Object.keys(localStorage).length===0 && Object.keys(sessionStorage).length===0 && !location.search && location.hash==="#/patient/questionnaires/"+readRoute().questionnaireId'))
            b.evaluate(pa,'window.fetch=qOriginalFetch')
        route(pa,'/patient/questionnaires/nonexistent')
        check('unknown questionnaire has return link',b.evaluate(pa,'document.body.innerText.includes("Опросник не найден") && [...document.querySelectorAll("a")].some(a=>a.hash==="#/patient/questionnaires")'))
'''
anchor='        # Layout and retained local features, in each required width.\n'
assert code.count(anchor)==1
code=code.replace(anchor,supplement+anchor)
sys.argv=[str(source),'--base-url','http://127.0.0.1:18009','--mail-url','http://127.0.0.1:18029','--compose-env-file','/tmp/work0009-config','--project','veganmedtech-work0009-test','--bidi-port','19239','--output',str(ROOT/'docs/quality/reports/2026-10-21-work-0009-browser.json')]
exec(compile(code,str(source),'exec'),{'__name__':'__main__','__file__':str(source)})
