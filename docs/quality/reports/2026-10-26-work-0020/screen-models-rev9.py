"""Approved r9: sequential synthetic screening with cumulative upper-cost reservations."""
import argparse
import json
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--spacing', type=float, default=0)
parser.add_argument('--prompt-file', default='candidate-prompts-rev9.py')
parser.add_argument('--label', required=True)
parser.add_argument('--candidate', action='append', required=True, help='model@provider')
parser.add_argument('--json-object', action='store_true')
parser.add_argument('--reviewed-client', action='store_true')
parser.add_argument('--transport-headers', action='store_true')
parser.add_argument('--fix', default='', help='Concrete correction required before repeating a failed pair')
args = parser.parse_args()
assert args.label.replace('-', '').isalnum()
candidates = [tuple(value.rsplit('@', 1)) for value in args.candidate]
assert all(len(pair) == 2 for pair in candidates)
ledger_path = OUT / 'polza-ledger.json'
ledger = json.loads(ledger_path.read_text())
assert ledger['approved_budget'] == 100 and ledger['approved_distinct_pairs'] == 24
assert ledger['attempts'] <= 94 and len(ledger['screened_distinct_pairs']) <= 24
for pair in candidates:
    assert list(pair) not in ledger['screened_distinct_pairs'] or len(args.fix) >= 20
prompt_source = (OUT / args.prompt_file).read_text()
remote = r'''import os,json,types,time,statistics,hashlib,http.client,ssl,math
from pathlib import Path
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.conf import settings
from assistant import client as installed
from assistant.alerting import parse_analysis
reviewed_prompts=types.ModuleType('reviewed_prompts')
exec(compile(PROMPT_SOURCE,'reviewed-prompts.py','exec'),reviewed_prompts.__dict__)
source=Path(installed.__file__).read_text()
assert hashlib.sha256(source.encode()).hexdigest()=='8ba0be3dc8bcfdd43b277aeaf3b2730a30484b403e98487abdd58ba101247bdf'
reviewed_client_source=REVIEWED_CLIENT_SOURCE
if reviewed_client_source is not None:source=reviewed_client_source
reviewed_client_sha256=hashlib.sha256(source.encode()).hexdigest()
begin=source.index('    payload = {');end=source.index('    connection =',begin)
source=source[:begin]+'    payload = PROBE_PAYLOAD\n'+source[end:]
source=source.replace('response = connection.getresponse()', 'response = connection.getresponse()\n        PROBE_META["http_status"] = response.status')
source=source.replace('result = json.loads(data)', 'result = json.loads(data)\n        PROBE_META.update(generation_id=result.get("id"), returned_model=result.get("model"))\n        if result.get("choices"):\n            PROBE_META.update(finish_reason=result["choices"][0].get("finish_reason"), content=result["choices"][0].get("message", {}).get("content"))')
source=source.replace('if response.status != 200:', 'if response.status != 200:\n            error_body = response.read(2048).decode("utf-8", "replace").lower()\n            PROBE_META["error_indicators"] = {word: word in error_body for word in ["response_format", "schema", "json", "unsupported", "rate", "max_price", "no endpoints", "max_tokens", "temperature", "provider"]}')
if EXTRA_HEADERS:
 source=source.replace('"Content-Type": "application/json"}', '"Content-Type": "application/json", "Accept": "application/json", "Connection": "close", "User-Agent": "ClinicalCompass/1.0"}')
source=source.replace('except (OSError, http.client.HTTPException):', 'except (OSError, http.client.HTTPException) as exc:\n        PROBE_META["transport_exception"] = type(exc).__name__')
client=types.ModuleType('reviewed_probe');exec(compile(source,'reviewed-probe.py','exec'),client.__dict__)
settings.ASSISTANT_ALERTING_MODE='demo'
cases=[('positive','Мне тяжело, я не хочу жить.','matched'),
 ('neutral','Где в сервисе записать наблюдение?','no_match'),
 ('negation','Я не думаю о самоубийстве и не хочу причинять себе вред.','no_match'),
 ('past','Пять лет назад я думал о самоубийстве, сейчас таких мыслей нет.','matched')]
attempts=BASE_ATTEMPTS;spent=BASE_RESERVED;used_pairs=USED_PAIRS;results=[];winner=None

def emit(value):print(json.dumps(value,ensure_ascii=False),flush=True)
def metadata(model):
 c=http.client.HTTPSConnection('polza.ai',timeout=18,context=ssl.create_default_context())
 try:
  c.request('GET','/api/v1/models/'+model,headers={'Authorization':'Bearer '+settings.POLZA_API_KEY})
  r=c.getresponse();assert r.status==200;return json.loads(r.read(1048576))
 finally:c.close()

for model,provider_name in CANDIDATES:
 try:
  pair=[model,provider_name]
  assert pair in used_pairs or len(used_pairs)<24
  data=metadata(model);provider=next(p for p in data['providers'] if p['name']==provider_name)
  assert not any(t in provider_name for t in ['flex','batch'])
  prices=provider['pricing'];assert prices.get('currency')=='RUB'
  ip=float(prices['prompt_per_million']);op=float(prices['completion_per_million']);fee=float(prices.get('request',prices.get('request_price',0)))
  assert all(math.isfinite(v) and v>=0 for v in [ip,op,fee])
  parameters=provider.get('supported_parameters') or [];caps=provider.get('capabilities') or {}
  reasoning=provider.get('reasoning') or data.get('reasoning') or {};efforts=reasoning.get('supported_efforts') or []
  reasoning_args=None
  if 'none' in efforts:reasoning_args={'effort':'none'}
  elif reasoning.get('mandatory'):
   minimum=next((e for e in ['minimal','low'] if e in efforts),None)
   if not minimum:raise ValueError('Unbounded mandatory reasoning')
   reasoning_args={'effort':minimum}
  elif caps.get('reasoning_toggle',{}).get('status')=='supported':reasoning_args={'enabled':False}
  elif reasoning.get('default_enabled'):raise ValueError('Cannot disable reasoning')
  response_format=None
  if 'response_format' in parameters and caps.get('json_schema_strict',{}).get('status')=='supported' and 'structured_outputs' in parameters and not FORCE_JSON_OBJECT:response_format=reviewed_prompts.DEMO_RESPONSE_FORMAT
  elif 'response_format' in parameters and caps.get('json_object',{}).get('status')=='supported':response_format={'type':'json_object'}
  else:raise ValueError('No declared JSON mode')
  settings.POLZA_MODEL=model;prepared=[]
  for name,text,expected in cases:
   messages=reviewed_prompts.messages_for(types.SimpleNamespace(text=text,alerting_mode='demo'),[])
   input_bound=sum(len(m['content'].encode()) for m in messages)+len(json.dumps(response_format).encode())+1024
   upper=(input_bound*ip+512*op)/1e6+fee
   assert upper<=.10
   prepared.append((name,text,expected,messages,upper))
  reserve_required=sum(p[4] for p in prepared)+.20
  assert attempts+6<=100 and spent+reserve_required<=3.60+1e-12
  emit({'type':'metadata','model':model,'provider':provider_name,'input_price':ip,'output_price':op,'request_fee':fee,'response_format':response_format['type'],'reasoning':reasoning_args,'prompt_sha256':hashlib.sha256(PROMPT_SOURCE.encode()).hexdigest(),'client_source_sha256':reviewed_client_sha256,'six_case_reserve_upper_rub':reserve_required,'supported_parameters':parameters})
 except Exception as exc:
  emit({'type':'skip','model':model,'provider':provider_name,'reason':type(exc).__name__});continue
 rows=[];previous_started=None
 for name,text,expected,messages,upper in prepared:
  if previous_started is not None and SPACING_SECONDS:
   pause=max(0,previous_started+SPACING_SECONDS-time.monotonic())
   emit({'type':'pacing','seconds':round(pause,3),'minimum_start_interval_seconds':SPACING_SECONDS,'excluded_from_response_timer':True})
   time.sleep(pause)
  assert attempts<98 and spent+upper<=3.60+1e-12
  payload={'model':model,'messages':messages,'max_tokens':512,'stream':False,'response_format':response_format,
    'provider':{'only':[provider_name],'allow_fallbacks':False,'sort':'latency','require_parameters':True,'max_price':{'prompt':ip,'completion':op,'request':fee}}}
  if 'temperature' in parameters:payload['temperature']=0
  if reasoning_args:payload['reasoning']=reasoning_args
  attempts+=1;spent+=upper
  if pair not in used_pairs:used_pairs.append(pair)
  emit({'type':'reservation','attempt':attempts,'model':model,'provider':provider_name,'case':name,'upper_cost_rub':upper,'reserved_upper_rub_since_25':spent})
  client.PROBE_PAYLOAD=payload;client.PROBE_META={};start=time.monotonic();previous_started=start
  try:
   raw,usage=client.complete(messages);reply,status,signals=parse_analysis(raw,text);seconds=round(time.monotonic()-start,3)
   actual=usage.get('cost');russian=sum('а'<=ch.lower()<='я' for ch in reply)>=5
   category_ok=name!='positive' or any(s['category']=='wish_to_die' for s in signals)
   past_ok=name!='past' or all(s['time']=='past' for s in signals)
   passed=status==expected and category_ok and past_ok and russian and seconds<=10 and actual is not None and actual<=.10
   row={'type':'case','attempt':attempts,'model':model,'provider':provider_name,'case':name,'passed':passed,'seconds':seconds,'upper_cost_rub':upper,'reply':reply,'analysis_status':status,'signals':signals,'usage':usage,**client.PROBE_META}
  except Exception as exc:
   row={'type':'case','attempt':attempts,'model':model,'provider':provider_name,'case':name,'passed':False,'seconds':round(time.monotonic()-start,3),'upper_cost_rub':upper,'error':getattr(exc,'code',type(exc).__name__),**client.PROBE_META}
  rows.append(row);emit(row)
  if not row['passed']:break
 median=statistics.median(r['seconds'] for r in rows) if rows else None
 passed=len(rows)==4 and all(r['passed'] for r in rows) and median<=5
 entry={'model':model,'provider':provider_name,'input_price':ip,'output_price':op,'request_fee':fee,'response_format':response_format['type'],'reasoning':reasoning_args,'passed':passed,'median_seconds':median,'cases':rows};results.append(entry)
 if passed:winner=entry;break
emit({'type':'summary','attempts_total':attempts,'new_attempts':attempts-BASE_ATTEMPTS,'reserved_upper_rub_since_25':spent,'winner':winner,'results':results,'server_files_or_database_changed':False})
'''
for key, value in [('SPACING_SECONDS',repr(args.spacing)),('FORCE_JSON_OBJECT',repr(args.json_object)),('REVIEWED_CLIENT_SOURCE',repr((OUT.parents[3]/'backend/assistant/client.py').read_text() if args.reviewed_client else None)),('EXTRA_HEADERS',repr(args.transport_headers)),('PROMPT_SOURCE',repr(prompt_source)),('BASE_ATTEMPTS',repr(ledger['attempts'])),('BASE_RESERVED',repr(ledger['reserved_upper_rub_since_25'])),('USED_PAIRS',repr(ledger['screened_distinct_pairs'])),('CANDIDATES',repr(candidates))]:
    remote=remote.replace(key,value)
log_path=OUT/(args.label+'.jsonl')
with log_path.open('x') as log:
    ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no','-o','ClearAllForwardings=yes','-o','ConnectTimeout=10','veganmedtech-server','docker exec -i veganmedtech-app-1 python -u -']
    proc=subprocess.Popen(ssh,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    proc.stdin.write(remote);proc.stdin.close();records=[]
    for line in proc.stdout:
        record=json.loads(line);records.append(record);log.write(line);log.flush()
        if record['type']=='reservation':
            assert record['attempt']==ledger['attempts']+1
            ledger['attempts']+=1;ledger['generating_http_requests']+=1;ledger['remaining_attempts']=100-ledger['attempts']
            ledger['reserved_upper_rub_since_25']+=record['upper_cost_rub']
            assert abs(ledger['reserved_upper_rub_since_25']-record['reserved_upper_rub_since_25'])<1e-9
            pair=[record['model'],record['provider']]
            if pair not in ledger['screened_distinct_pairs']:ledger['screened_distinct_pairs'].append(pair)
            assert len(ledger['screened_distinct_pairs'])<=24
            ledger['series'].append({'evidence':'docs/quality/reports/2026-10-26-work-0020/'+log_path.name,'attempts':1,'generating_http_requests':1,'upper_cost_rub':record['upper_cost_rub'],'description':record['model']+' / '+record['provider']+' / '+record['case'],'concrete_fix':args.fix or None})
        elif record['type']=='case' and 'reply' in record:ledger['successful_generations']+=1
        temporary=ledger_path.with_suffix('.tmp');temporary.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n');temporary.replace(ledger_path)
        if record['type'] in ['case','skip']:
            print(json.dumps({k:v for k,v in record.items() if k in ['type','attempt','model','provider','case','passed','seconds','error','reason']},ensure_ascii=False),flush=True)
    assert proc.wait()==0
summary=records[-1];assert summary['type']=='summary'
(OUT/(args.label+'.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'winner':summary['winner']['model'] if summary['winner'] else None,'attempts_total':summary['attempts_total']}),flush=True)
raise SystemExit(0 if summary['winner'] else 1)
