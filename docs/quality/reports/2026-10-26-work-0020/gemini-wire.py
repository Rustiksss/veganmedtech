"""Bounded synthetic transport control; credentials stay in memory on the server."""
import json
import subprocess
from pathlib import Path

out = Path(__file__).resolve().parent
ledger_path = out / 'polza-ledger.json'
ledger = json.loads(ledger_path.read_text())
assert ledger['attempts'] == 39 and ledger['approved_budget'] == 60
label = 'gemini-wire-rev8'
remote = r'''import subprocess,json,http.client,ssl,time,math
key=subprocess.check_output(['docker','exec','veganmedtech-app-1','python','-c','from django.conf import settings; import os; os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings"); print(settings.POLZA_API_KEY,end="")'],text=True)
assert key and '\n' not in key
model='google/gemini-2.5-flash-lite';provider='google-ai-studio'
c=http.client.HTTPSConnection('polza.ai',timeout=18,context=ssl.create_default_context())
c.request('GET','/api/v1/models/'+model,headers={'Authorization':'Bearer '+key})
r=c.getresponse();assert r.status==200;metadata=json.loads(r.read(1048576));c.close()
p=next(p for p in metadata['providers'] if p['name']==provider)
pricing=p['pricing'];assert pricing['currency']=='RUB'
ip=float(pricing['prompt_per_million']);op=float(pricing['completion_per_million']);fee=float(pricing.get('request',0))
assert all(math.isfinite(v) and v>=0 for v in [ip,op,fee])
assert not (p.get('reasoning') or metadata.get('reasoning') or {}).get('mandatory')
messages=[{'role':'user','content':'Ответь одним словом: привет.'}]
upper=((sum(len(m['content'].encode()) for m in messages)+1024)*ip+64*op)/1e6+fee
assert upper<=.1
payload={'model':model,'messages':messages,'max_tokens':64,'stream':False,'provider':{'only':[provider],'allow_fallbacks':False,'max_price':{'prompt':ip,'completion':op}}}
for attempt,protocol in [(40,'--http1.1')]:
 print(json.dumps({'type':'reservation','attempt':attempt,'model':model,'provider':provider,'case':protocol,'upper_cost_rub':upper}),flush=True)
 config='header = '+json.dumps('Authorization: Bearer '+key)+'\n'
 start=time.monotonic()
 q=subprocess.run(['curl','--silent','--show-error','--noproxy','*','--proto','=https',protocol,'--max-time','18','--connect-timeout','5','--config','-','--header','Content-Type: application/json','--data-binary',json.dumps(payload,ensure_ascii=False),'--write-out','\nCURL_META:%{json}','https://polza.ai/api/v1/chat/completions'],input=config,capture_output=True,text=True)
 body,sep,tail=q.stdout.rpartition('\nCURL_META:')
 meta=json.loads(tail) if sep else {}
 result={'type':'case','attempt':attempt,'protocol':protocol,'curl_exit':q.returncode,'seconds':round(time.monotonic()-start,3),'status':meta.get('http_code'),'http_version':meta.get('http_version'),'start_transfer':meta.get('time_starttransfer'),'upper_cost_rub':upper}
 try:
  data=json.loads(body)
  result['model']=data.get('model');result['generation_id']=data.get('id');result['usage']=data.get('usage')
  if data.get('choices'):
   result['reply']=data['choices'][0]['message'].get('content');result['finish_reason']=data['choices'][0].get('finish_reason')
  else:result['error_code']=(data.get('error') or {}).get('code')
 except (ValueError,TypeError):pass
 print(json.dumps(result,ensure_ascii=False),flush=True)
'''
ssh = ['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no','-o','ClearAllForwardings=yes','-o','ConnectTimeout=10','veganmedtech-server','python3 -u -']
proc = subprocess.Popen(ssh, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
proc.stdin.write(remote)
proc.stdin.close()
with (out / (label+'.jsonl')).open('x') as log:
    for line in proc.stdout:
        record = json.loads(line)
        log.write(line); log.flush()
        if record['type'] == 'reservation':
            assert record['attempt'] == ledger['attempts'] + 1
            ledger['attempts'] += 1
            ledger['generating_http_requests'] += 1
            ledger['remaining_attempts'] = 60-ledger['attempts']
            ledger['series'].append({'evidence':'docs/quality/reports/2026-10-26-work-0020/'+label+'.jsonl','attempts':1,'generating_http_requests':1,'description':record['model']+' / '+record['provider']+' / '+record['case']+' / minimal benign'})
        elif record.get('reply'):
            ledger['successful_generations'] += 1
        ledger_path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(record,ensure_ascii=False),flush=True)
assert proc.wait() == 0
