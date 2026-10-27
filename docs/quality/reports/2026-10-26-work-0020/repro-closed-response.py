"""No network: real HTTPResponse closes a Content-Length body after its last read1."""
import errno
import http.client
import io
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT=Path(__file__).resolve().parents[4]
conf=types.ModuleType('django.conf')
conf.settings=types.SimpleNamespace(POLZA_API_KEY='synthetic-placeholder',POLZA_MODEL='deepseek/deepseek-v4-flash')
sys.modules['django']=types.ModuleType('django');sys.modules['django.conf']=conf
client=types.ModuleType('reviewed_client');exec(compile((ROOT/'backend/assistant/client.py').read_text(),'client.py','exec'),client.__dict__)
body=json.dumps({'model':conf.settings.POLZA_MODEL,'choices':[{'message':{'content':'Учебный ответ.'},'finish_reason':'stop'}],'usage':{'cost':.001}}).encode()
class Socket:
    def __init__(self):
        self.fp=io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)
        self.closed_timeout_calls=0
    def makefile(self,*args):return self.fp
    def settimeout(self,value):
        if self.fp.closed:
            self.closed_timeout_calls+=1
            raise OSError(errno.EBADF,'Synthetic closed socket')
sock=Socket();response=http.client.HTTPResponse(sock);response.begin()
connection=MagicMock();connection.sock=sock;connection.getresponse.return_value=response
with patch.object(client.http.client,'HTTPSConnection',return_value=connection):
    try:
        reply,usage=client.complete([{'role':'user','content':'Вымышленный текст'}])
        result={'passed':reply=='Учебный ответ.','outcome':'completed','closed_timeout_calls':sock.closed_timeout_calls,'response_closed':response.isclosed(),'network_requests':0}
    except client.ProviderError as exc:
        result={'passed':False,'outcome':exc.code,'closed_timeout_calls':sock.closed_timeout_calls,'response_closed':response.isclosed(),'network_requests':0}
print(json.dumps(result,ensure_ascii=False))
raise SystemExit(0 if result['passed'] else 1)
