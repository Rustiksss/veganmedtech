"""Approved r8: bounded, sequential synthetic screening; no production changes."""
import argparse,json,subprocess
from pathlib import Path

OUT=Path(__file__).resolve().parent
ledger_path=OUT/'polza-ledger.json'
parser=argparse.ArgumentParser();parser.add_argument('--compact',action='store_true');args=parser.parse_args()
ledger=json.loads(ledger_path.read_text())
assert ledger['approved_budget']==60
base_attempts=ledger['attempts']
assert args.compact and base_attempts==45
label='screen-compact-routes-rev8'
prompt_source=(OUT.parents[3]/'backend/assistant/prompts.py').read_text() if args.compact else None
remote=r'''import os,json,types,time,statistics,hashlib,http.client,ssl,math
from pathlib import Path
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.conf import settings
from assistant import client as installed
from assistant.alerting import parse_analysis
from assistant.prompts import messages_for
PROMPT_OVERRIDE
source=Path(installed.__file__).read_text()
assert hashlib.sha256(source.encode()).hexdigest()=='8ba0be3dc8bcfdd43b277aeaf3b2730a30484b403e98487abdd58ba101247bdf'
begin=source.index('    payload = {');end=source.index('    connection =',begin)
source=source[:begin]+'    payload = PROBE_PAYLOAD\n'+source[end:]
source=source.replace('result = json.loads(data)', 'result = json.loads(data)\n        PROBE_META.update(generation_id=result.get("id"), returned_model=result.get("model"), choice_count=len(result.get("choices", [])), response_keys=list(result))\n        if result.get("choices"):\n            PROBE_META.update(finish_reason=result["choices"][0].get("finish_reason"), content=result["choices"][0].get("message", {}).get("content"))')
client=types.ModuleType('reviewed_probe');exec(compile(source,'reviewed-probe.py','exec'),client.__dict__)
settings.ASSISTANT_ALERTING_MODE='demo'
candidates=CANDIDATES
cases=[('positive','Мне тяжело, я не хочу жить.','matched'),
 ('neutral','Где в сервисе записать наблюдение?','no_match'),
 ('negation','Я не думаю о самоубийстве и не хочу причинять себе вред.','no_match'),
 ('past','Пять лет назад я думал о самоубийстве, сейчас таких мыслей нет.','matched')]
attempts=BASE_ATTEMPTS;results=[];winner=None
def emit(value):print(json.dumps(value,ensure_ascii=False),flush=True)
def metadata(model):
 c=http.client.HTTPSConnection('polza.ai',timeout=18,context=ssl.create_default_context())
 try:
  c.request('GET','/api/v1/models/'+model,headers={'Authorization':'Bearer '+settings.POLZA_API_KEY})
  r=c.getresponse();assert r.status==200;return json.loads(r.read(1048576))
 finally:c.close()
for model,provider_name in candidates:
 try:
  data=metadata(model)
  providers=data.get('providers') or [data.get('top_provider',{})]
  provider=next(p for p in providers if p.get('name')==provider_name)
  assert not any(t in provider_name for t in ['flex','batch'])
  prices=provider['pricing'];assert prices.get('currency')=='RUB'
  input_price=float(prices['prompt_per_million']);output_price=float(prices['completion_per_million'])
  fee=float(prices.get('request',prices.get('request_price',0)))
  assert all(math.isfinite(v) and v>=0 for v in [input_price,output_price,fee])
  parameters=provider.get('supported_parameters') or []
  reasoning=provider.get('reasoning') or data.get('reasoning') or {}
  efforts=reasoning.get('supported_efforts') or []
  reasoning_args=None
  if 'none' in efforts:reasoning_args={'effort':'none'}
  elif reasoning.get('mandatory'):
   minimum=next((e for e in ['minimal','low'] if e in efforts),None)
   if not minimum:raise ValueError('No bounded documented minimal reasoning')
   reasoning_args={'effort':minimum}
  elif reasoning.get('default_enabled'):
   if 'reasoning' not in parameters:raise ValueError('Cannot disable default reasoning')
   reasoning_args={'enabled':False}
  caps=provider.get('capabilities') or {}
  json_mode='response_format' in parameters and caps.get('json_object',{}).get('status')=='supported'
  emit({'type':'metadata','model':model,'provider':provider_name,'input_price':input_price,'output_price':output_price,'request_fee':fee,'json_mode':json_mode,'reasoning':reasoning_args})
 except Exception as exc:
  emit({'type':'skip','model':model,'provider':provider_name,'reason':type(exc).__name__});continue
 settings.POLZA_MODEL=model;rows=[]
 for name,text,expected in cases:
  messages=messages_for(types.SimpleNamespace(text=text,alerting_mode='demo'),[])
  input_bound=sum(len(m['content'].encode('utf-8')) for m in messages)+len(json.dumps(reviewed_prompts.DEMO_RESPONSE_FORMAT).encode())+1024
  upper=(input_bound*input_price+512*output_price)/1000000+fee
  if upper>.10 or attempts>=60:
   emit({'type':'skip','model':model,'provider':provider_name,'case':name,'reason':'price_or_attempt_limit','upper_cost_rub':upper});break
  payload={'model':model,'messages':messages,'max_tokens':512,'stream':False,
   'provider':{'only':[provider_name],'allow_fallbacks':False,'sort':'latency','max_price':{'prompt':input_price,'completion':output_price}}}
  if json_mode:
   payload['response_format']=reviewed_prompts.DEMO_RESPONSE_FORMAT if caps.get('json_schema_strict',{}).get('status')=='supported' and 'structured_outputs' in parameters else {'type':'json_object'}
   payload['provider']['require_parameters']=True
  if 'temperature' in parameters:payload['temperature']=0
  if reasoning_args:payload['reasoning']=reasoning_args
  attempts+=1;emit({'type':'reservation','attempt':attempts,'model':model,'provider':provider_name,'case':name,'upper_cost_rub':upper})
  client.PROBE_PAYLOAD=payload;client.PROBE_META={};start=time.monotonic()
  try:
   raw,usage=client.complete(messages)
   reply,status,signals=parse_analysis(raw,text)
   seconds=round(time.monotonic()-start,3)
   actual=usage.get('cost');russian=sum('а'<=ch.lower()<='я' for ch in reply)>=5
   passed=status==expected and russian and seconds<=10 and actual is not None and actual<=.10 and (name!='past' or all(s['time']=='past' for s in signals))
   row={'type':'case','attempt':attempts,'model':model,'provider':provider_name,'case':name,'passed':passed,'seconds':seconds,'upper_cost_rub':upper,'reply':reply,'analysis_status':status,'signals':signals,'usage':usage,**client.PROBE_META}
  except Exception as exc:
   row={'type':'case','attempt':attempts,'model':model,'provider':provider_name,'case':name,'passed':False,'seconds':round(time.monotonic()-start,3),'upper_cost_rub':upper,'error':getattr(exc,'code',type(exc).__name__),**client.PROBE_META}
  rows.append(row);emit(row)
  if not row['passed']:break
 median=statistics.median(r['seconds'] for r in rows) if rows else None
 passed=len(rows)==4 and all(r['passed'] for r in rows) and median<=5
 entry={'model':model,'provider':provider_name,'input_price':input_price,'output_price':output_price,'request_fee':fee,'json_mode':json_mode,'reasoning':reasoning_args,'passed':passed,'median_seconds':median,'cases':rows};results.append(entry)
 if passed:winner=entry;break
emit({'type':'summary','attempts_total':attempts,'new_attempts':attempts-BASE_ATTEMPTS,'winner':winner,'results':results,'server_files_or_database_changed':False})
'''
original_candidates=[('upstage/solar-mini4', 'upstage/zdr'), ('ibm-granite/granite-4.0-h-micro', 'cloudflare'), ('qwen/qwen3.8-27b', 'tenstorrent/fp4'), ('nex-agi/nex-n2.5-mini', 'nex-agi/bf16'), ('qwen/qwen3.5-9b', 'polza'), ('deepseek/deepseek-v4.1-flash-1017', 'open-inference/fp4'), ('amazon/nova-micro-v1', 'amazon-bedrock'), ('nvidia/nemotron-3-nano-30b-a3b', 'novita/fp4'), ('amazon/nova-lite-v1', 'amazon-bedrock'), ('upstage/solar-mini4', 'upstage')]
override=''
if args.compact:
    override="reviewed_prompts=types.ModuleType('reviewed_prompts');exec(compile("+repr(prompt_source)+",'reviewed-prompts.py','exec'),reviewed_prompts.__dict__);messages_for=reviewed_prompts.messages_for"
remote=remote.replace('PROMPT_OVERRIDE',override).replace('CANDIDATES',repr([('upstage/solar-mini4','upstage'),('nex-agi/nex-n2.5-mini','nex-agi/bf16'),('amazon/nova-micro-v1','amazon-bedrock')] if args.compact else original_candidates)).replace('BASE_ATTEMPTS',repr(base_attempts))
ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no','-o','ClearAllForwardings=yes','veganmedtech-server','docker exec -i veganmedtech-app-1 python -u -']
proc=subprocess.Popen(ssh,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
proc.stdin.write(remote);proc.stdin.close()
records=[]
with (OUT/(label+'.jsonl')).open('x') as log:
    for line in proc.stdout:
        log.write(line);log.flush()
        record=json.loads(line);records.append(record)
        if record['type']=='reservation':
            assert record['attempt']==ledger['attempts']+1
            ledger['attempts']+=1;ledger['generating_http_requests']+=1;ledger['remaining_attempts']=60-ledger['attempts']
            ledger['series'].append({'evidence':'docs/quality/reports/2026-10-26-work-0020/'+label+'.jsonl','attempts':1,'generating_http_requests':1,'description':record['model']+' / '+record['provider']+' / '+record['case']})
            ledger_path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')
        elif record['type']=='case':
            if 'reply' in record:
                ledger['successful_generations']+=1;ledger_path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({k:record[k] for k in ['type','attempt','model','provider','case','passed','seconds','error'] if k in record}),flush=True)
    code=proc.wait();assert code==0,code
summary=records[-1];assert summary['type']=='summary'
(OUT/(label+'.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'winner':summary['winner']['model'] if summary['winner'] else None,'attempts_total':summary['attempts_total']}),flush=True)
raise SystemExit(0 if summary['winner'] else 1)
