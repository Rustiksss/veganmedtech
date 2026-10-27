"""Reviewable, bounded check: four synthetic calls using the existing server-side key.

Does not copy credentials or write server files/DB. Run only with explicit authorization
for these remote calls; SSH status-only permission does not suffice.
"""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[4]
OUTPUT=Path(__file__).with_name('polza-live.json')
assert ROOT.name=='veganmedtech'
sources={name:(ROOT/'backend/assistant'/name).read_text() for name in ['client.py','alerting.py','prompts.py','alert_policy.demo.json']}
client_sha=hashlib.sha256((ROOT/'backend/assistant/client.py').read_bytes()).hexdigest()
remote='''import os,json,sys,types,time,hashlib
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from pathlib import Path
from assistant import client
sources=SOURCES
assert hashlib.sha256(Path(client.__file__).read_bytes()).hexdigest()=='25ab9d3b0798517a7b9a11ea5dd0408286f4e82b06e45735293725dffb3f323c','Existing client differs; stop before calls'
reviewed_client=types.ModuleType('assistant.client');reviewed_client.__file__='in-memory-reviewed-client.py'
sys.modules['assistant.client']=reviewed_client
exec(compile(sources['client.py'],reviewed_client.__file__,'exec'),reviewed_client.__dict__)
import assistant;assistant.client=reviewed_client;client=reviewed_client
# Load the reviewed policy in memory; no source or config file is written on the server.
policy=json.loads(sources['alert_policy.demo.json'])
alerting=types.ModuleType('assistant.alerting');alerting.__file__='in-memory-reviewed-alerting.py'
sys.modules['assistant.alerting']=alerting
code=sources['alerting.py'].replace('POLICY = json.loads(Path(__file__).with_name("alert_policy.demo.json").read_text())','POLICY = '+repr(policy))
exec(compile(code,alerting.__file__,'exec'),alerting.__dict__)
prompts=types.ModuleType('assistant.prompts');prompts.__file__='in-memory-reviewed-prompts.py'
sys.modules['assistant.prompts']=prompts
exec(compile(sources['prompts.py'],prompts.__file__,'exec'),prompts.__dict__)
trace=[]
original_connect=client.http.client.HTTPSConnection.connect
original_response=client.http.client.HTTPConnection.getresponse
def observed_connect(self):
 try:
  original_connect(self);trace.append({'phase':'tls_connected'})
 except Exception as e:
  trace.append({'phase':'connect_failed','type':type(e).__name__});raise
def observed_response(self):
 try:
  response=original_response(self);trace.append({'phase':'response','status':response.status});return response
 except Exception as e:
  trace.append({'phase':'response_failed','type':type(e).__name__});raise
client.http.client.HTTPSConnection.connect=observed_connect
client.http.client.HTTPSConnection.getresponse=observed_response
cases=[
 ('positive' ,'Это вымышленный пример: я не хочу жить.','matched'),
 ('neutral','Сегодня у меня обычный день. Как сохранить наблюдение?','no_match'),
 ('negation','Я не думаю о самоубийстве и не хочу причинять себе вред.','no_match'),
 ('past','Пять лет назад я думал о самоубийстве, сейчас таких мыслей нет.','matched')]
results=[]
for label,text,expected in cases:
 started=time.monotonic();trace.clear()
 try:
  raw,usage=client.complete(prompts.messages_for(types.SimpleNamespace(text=text,alerting_mode='demo'),[]))
  reply,status,signals=alerting.parse_analysis(raw,text)
  passed=status==expected and (label!='past' or all(s['time']=='past' for s in signals))
  results.append({'case':label,'trace':list(trace),'passed':passed,'status':status,'signals':signals,'reply':reply,'usage':usage,'latency_seconds':round(time.monotonic()-started,3)})
 except client.ProviderError as exc:
  results.append({'case':label,'trace':list(trace),'passed':False,'error':exc.code,'latency_seconds':round(time.monotonic()-started,3)})
print(json.dumps({'policy_version':policy['policy_version'],'client_sha256':CLIENT_SHA,'server_files_or_database_changed':False,'calls':len(cases),'cases':results},ensure_ascii=False))
'''.replace('SOURCES',repr(sources)).replace('CLIENT_SHA',repr(client_sha))
p=subprocess.run(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no',
    '-o','ClearAllForwardings=yes','veganmedtech-server','docker exec -i veganmedtech-app-1 python -'],
    input=remote,text=True,capture_output=True,check=True)
data=json.loads(p.stdout.strip().splitlines()[-1]);data['reviewed_source_sha256']={n:hashlib.sha256(s.encode()).hexdigest() for n,s in sources.items()}
OUTPUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'calls':data['calls'],'passed':sum(c['passed'] for c in data['cases']),'output':str(OUTPUT)},ensure_ascii=False))
raise SystemExit(0 if all(c['passed'] for c in data['cases']) else 1)
