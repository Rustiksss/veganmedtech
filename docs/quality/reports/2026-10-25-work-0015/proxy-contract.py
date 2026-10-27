"""Actual Caddy contract, isolated loopback HTTP and synthetic credentials only."""
import base64,http.server,json,os,re,subprocess,threading,time,socket,urllib.request,urllib.error
from pathlib import Path
class Echo(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200);self.end_headers();self.wfile.write(json.dumps(dict(self.headers)).encode())
 def log_message(self,*args):pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Echo);
echo=server.server_port
def free_port():
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]
main,mail=free_port(),free_port()
threading.Thread(target=server.serve_forever,daemon=True).start()
s=Path('deploy/Caddyfile').read_text();s=s[s.index('https://94.103.3.149 {'):]
s=re.sub(r'\ttls \{\n.*?\n\t\}\n','',s,flags=re.S)
s=s.replace('https://94.103.3.149:8443 {',f'http://127.0.0.1:{mail} {{\n\tbind 127.0.0.1').replace('https://94.103.3.149 {',f'http://127.0.0.1:{main} {{\n\tbind 127.0.0.1').replace('127.0.0.1:18008',f'127.0.0.1:{echo}').replace('127.0.0.1:18025',f'127.0.0.1:{echo}')
p=Path('/tmp/work0015/contract.Caddyfile');p.write_text('{\n admin off\n}\n'+s)
password='SYNTHETIC-CONTRACT-PASSWORD-WORK0015'
env=dict(os.environ,MAILPIT_PASSWORD_HASH=subprocess.check_output(['/tmp/work0015/caddy','hash-password','--bcrypt-cost','14'],input=(password+'\n').encode()).decode().strip())
log=open('/tmp/work0015/proxy-contract.log','w');proc=subprocess.Popen(['/tmp/work0015/caddy','run','--config',str(p),'--adapter','caddyfile'],env=env,stdout=log,stderr=log)
checks=[]
def check(name,value):checks.append(dict(name=name,passed=bool(value)));assert value,name
def request(path,auth=None,extra=None):
 headers=dict(extra or {})
 if auth:headers['Authorization']='Basic '+base64.b64encode(auth.encode()).decode()
 try:return urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{mail}'+path,headers=headers),timeout=6)
 except urllib.error.HTTPError as error:return error
try:
 for _ in range(50):
  try:
   with request('/') as response:
    if response.status==401:break
  except OSError:time.sleep(.1)
 for auth in [None,'operator:incorrect']:
  for path in ['/','/assets/app.js','/api/v1/messages','/api/events','//api/v1/messages','/%61pi/v1/messages']:
   with request(path,auth) as response:check(('anonymous' if auth is None else 'wrong password')+' rejected '+path,response.status==401)
 with request('/api/events',extra={'Connection':'Upgrade','Upgrade':'websocket','Sec-WebSocket-Version':'13','Sec-WebSocket-Key':'eDEyMzQ1Njc4OTAxMjM0NQ=='}) as response:check('anonymous websocket upgrade rejected',response.status==401)
 extra={'Cookie':'sessionid=SYNTHETIC-COOKIE','Origin':f'http://127.0.0.1:{mail}','X-Forwarded-For':'8.8.8.8','X-Real-IP':'8.8.8.8','X-Forwarded-Proto':'http','X-Forwarded-Host':'evil.example','Forwarded':'for=8.8.8.8'}
 with request('/api/v1/messages','operator:'+password,extra) as response:
  check('operator allowed',response.status==200);check('mailbox no-store',response.headers.get('Cache-Control')=='no-store');headers={k.lower():v for k,v in json.load(response).items()}
 check('Host retains port',headers['host']==f'127.0.0.1:{mail}');check('Origin preserved',headers['origin']==f'http://127.0.0.1:{mail}')
 for name in ['cookie','authorization','forwarded','x-forwarded-host']:check(name+' removed',name not in headers)
 check('proxy protocol replaced',headers['x-forwarded-proto']=='https');check('client address replaced',headers['x-forwarded-for']=='127.0.0.1' and headers['x-real-ip']=='127.0.0.1')
 with urllib.request.urlopen(f'http://127.0.0.1:{main}/') as response:check('main site remains public',response.status==200 and not response.headers.get('WWW-Authenticate'))
 print(json.dumps(dict(checks=checks),indent=2))
finally:
 proc.terminate();proc.wait(timeout=10);server.shutdown();log.close()
