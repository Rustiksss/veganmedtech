import base64,json,secrets,sys,urllib.request
from pathlib import Path
sys.path.insert(0,'tests/browser');from bidi import Browser
import websocket
url=Path('/tmp/work0015/local-url.txt').read_text();private=json.loads(Path('/tmp/work0015/credentials/config/mailpit-access.json').read_text());authorization='Basic '+base64.b64encode((private['username']+':'+private['password']).encode()).decode();b=Browser(19258,accept_insecure=False,basic_auth=dict(origin=url,username=private['username'],password=private['password']));checks=[]
def check(name,value):checks.append(dict(name=name,passed=bool(value)));assert value,name
try:
 ws=websocket.create_connection(url.replace('http:','ws:')+'/api/events',header={'Authorization':authorization},origin=url,timeout=8);check('real operator WebSocket upgrade',ws.getstatus()==101);ws.close()
 try:ws=websocket.create_connection(url.replace('http:','ws:')+'/api/events',header={'Authorization':authorization},origin='http://foreign.example.test',timeout=8)
 except websocket.WebSocketBadStatusException as error:check('foreign Origin denied',error.status_code==403)
 else:ws.close();check('foreign Origin denied',False)
 c=b.context(private=True);b.navigate(c,url+'/');b.wait(c,'!document.body.innerText.includes("Loading messages...")')
 started=b.evaluate(c,'performance.timeOrigin')
 label='WORK-0015 local acceptance '+secrets.token_hex(4)
 data=dict(From=dict(Email='no-reply@example.test',Name='WORK-0015'),To=[dict(Email='work0015-local@example.test')],Subject=label,Text='Синтетическая проверка WORK-0015.')
 with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:32768/api/v1/send',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})) as r:check('own synthetic message accepted',r.status==200)
 b.wait(c,'document.body.innerText.includes('+json.dumps(label)+')');check('new letter visible without reload',b.evaluate(c,'performance.timeOrigin')==started)
 b.evaluate(c,'[...document.querySelectorAll("a")].find(x=>x.innerText==='+json.dumps(label)+').click()')
 b.wait(c,'document.body.innerText.includes("Синтетическая проверка WORK-0015.")');check('letter opened',True)
 for width in [1440,390]:
  b.viewport(c,width)
  check('layout '+str(width),b.evaluate(c,'document.documentElement.scrollWidth<=innerWidth+1 && !!document.querySelector('+json.dumps('[title="Return to messages"]')+')'))
 print(json.dumps(dict(environment='isolated loopback HTTP, synthetic credentials/mail only; public TLS not tested yet',checks=checks),indent=2))
finally:b.close()
