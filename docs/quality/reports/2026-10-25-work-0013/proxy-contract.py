import base64,http.server,json,os,re,subprocess,threading,time,urllib.request,urllib.error
from pathlib import Path
class Echo(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200);self.end_headers();self.wfile.write(json.dumps(dict(self.headers)).encode())
 def log_message(self,*args): pass
server=http.server.HTTPServer(('127.0.0.1',18444),Echo);threading.Thread(target=server.serve_forever,daemon=True).start()
s=Path('deploy/Caddyfile').read_text();s=s[s.index('https://94.103.3.149 {'):];s=re.sub(r'    tls \{\n.*?\n    \}\n','',s,flags=re.S).replace('https://94.103.3.149 {','http://127.0.0.1:18443 {\n    bind 127.0.0.1').replace('127.0.0.1:18008','127.0.0.1:18444')
p=Path('/tmp/work0013-local/contract.Caddyfile');p.write_text('{\n admin off\n}\n'+s)
env=dict(os.environ);password='Synthetic-contract-password-73';env['DEMO_PASSWORD_HASH']=subprocess.check_output(['/tmp/work0013-caddy','hash-password'],input=(password+'\n').encode()).decode().strip()
log=open('/tmp/work0013-local/proxy-contract.log','w');proc=subprocess.Popen(['/tmp/work0013-caddy','run','--config',str(p),'--adapter','caddyfile'],env=env,stdout=log,stderr=log)
checks=[]
def check(name,value):
 checks.append(dict(name=name,passed=bool(value)));assert value,name
try:
 for _ in range(50):
  try:
   urllib.request.urlopen('http://127.0.0.1:18443/',timeout=1)
  except urllib.error.HTTPError as e:
   if e.code==401:break
  except OSError:time.sleep(.1)
 for path in ['/', '/api/me','/static/js/questionnaires.js']:
  try:urllib.request.urlopen('http://127.0.0.1:18443'+path);raise AssertionError('gate absent')
  except urllib.error.HTTPError as e:check('anonymous blocked '+path,e.code==401)
 auth='Basic '+base64.b64encode(('demo:'+password).encode()).decode()
 req=urllib.request.Request('http://127.0.0.1:18443/',headers=dict(Authorization=auth,**{'X-Forwarded-Proto':'http','X-Forwarded-For':'1.1.1.1,8.8.8.8','X-Real-IP':'8.8.8.8','Forwarded':'for=8.8.8.8;proto=http','X-Forwarded-Host':'evil.example'}))
 with urllib.request.urlopen(req) as r:d=json.load(r)
 headers={k.lower():v for k,v in d.items()}
 check('protocol replaced',headers['x-forwarded-proto']=='https');check('xff replaced',headers['x-forwarded-for']=='127.0.0.1');check('client IP replaced',headers['x-real-ip']=='127.0.0.1')
 for h in ['authorization','forwarded','x-forwarded-host']:check(h+' removed',h not in headers)
 print(json.dumps(checks))
finally:
 proc.terminate();proc.wait(timeout=10);server.shutdown();log.close()
