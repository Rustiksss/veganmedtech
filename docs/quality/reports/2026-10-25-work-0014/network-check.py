import json,socket,urllib.request,urllib.error
base='https://94.103.3.149';results={}
for path,expected in {'/':200,'/api/me':401,'/api/me/self-reports':401,'/api/questionnaires/module':401,'/frontend/static/js/questionnaires.js':404,'/backend/config/settings.py':404,'/misc_materials/':404,'/.env':404,'/static/staticfiles.json':200}.items():
 try:
  with urllib.request.urlopen(base+path,timeout=10) as response:status=response.status;headers=response.headers;body=response.read()
 except urllib.error.HTTPError as error:status=error.code;headers=error.headers;body=b''
 assert status==expected,(path,status)
 assert not headers.get('WWW-Authenticate','').lower().startswith('basic')
 if path.endswith('staticfiles.json'):
  manifest=json.loads(body)
  assert not any('questionnaires' in k or 'questionnaires' in v for k,v in manifest['paths'].items())
  results['manifest_has_no_questionnaire_module']=True
 results[path]=status
for port in [18008,18025,5432,2019]:
 sock=socket.socket();sock.settimeout(2)
 try:result=sock.connect_ex(('94.103.3.149',port))
 finally:sock.close()
 assert result!=0,port
 results['closed_port_'+str(port)]=True
print(json.dumps(dict(strict_trusted_https=True,checks=results),indent=2))
