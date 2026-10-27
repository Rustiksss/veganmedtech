"""Strict HTTPS/source identity and server-local backup verification for WORK-0019."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import urllib.request

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
BASE = 'https://94.103.3.149'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes', 'veganmedtech-server']


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        path = values.get('src' if tag == 'script' else 'href', '')
        if path.startswith('/static/') and tag in ['script', 'link']:
            self.paths.append(path)


parser = Assets()
with urllib.request.urlopen(BASE, timeout=15) as response:
    assert response.status == 200 and not response.headers.get('WWW-Authenticate')
    parser.feed(response.read().decode())
resources = {}
for prefix, source in [('js/app.', 'frontend/static/js/app.js'), ('css/app.', 'frontend/static/css/app.css'), ('js/api.', 'frontend/static/js/api.js')]:
    path = next(p for p in parser.paths if p.startswith('/static/' + prefix))
    with urllib.request.urlopen(urllib.request.Request(BASE + path, headers={'Cache-Control': 'no-cache'}), timeout=15) as response:
        digest = hashlib.sha256(response.read()).hexdigest()
    expected = hashlib.sha256((ROOT / source).read_bytes()).hexdigest()
    assert digest == expected
    resources[source] = dict(url=BASE + path, sha256=digest, matches_local=True)
with urllib.request.urlopen(BASE + '/health/ready', timeout=15) as response:
    assert json.load(response)['ready'] is True
code = '''import hashlib,json,os,subprocess
from pathlib import Path
root=Path('/opt/veganmedtech');current=(root/'current').resolve();previous=(root/'previous').resolve()
assert previous.name=='20261025T213505Z-81b7c2d9' and current!=previous
manifest=json.loads((current/'image.json').read_text())
backup=root/'backups'/(current.name+'.dump')
assert backup.is_file() and backup.stat().st_size>0
with backup.open('rb') as stream:
 subprocess.run(['docker','exec','-i','veganmedtech-db-1','pg_restore','--list'],stdin=stream,stdout=subprocess.DEVNULL,check=True)
subprocess.run(['docker','image','inspect','veganmedtech-server:20261025T213505Z-81b7c2d9'],stdout=subprocess.DEVNULL,check=True)
sources=PATHS
hashes={p:hashlib.sha256((current/p).read_bytes()).hexdigest() for p in sources}
health={name:subprocess.check_output(['docker','inspect','--format','{{.State.Health.Status}}',name],text=True).strip() for name in ['veganmedtech-app-1','veganmedtech-db-1','veganmedtech-mailpit-1']}
free=os.statvfs('/opt').f_bavail*os.statvfs('/opt').f_frsize
assert all(value=='healthy' for value in health.values()) and free>=268435456
print(json.dumps(dict(current=current.name,previous=previous.name,image_id=manifest['image_id'],image_tag=manifest['image_tag'],source_hashes=hashes,backup_bytes=backup.stat().st_size,pg_restore_list_passed=True,rollback_image_preserved=True,health=health,available_bytes=free)))
'''.replace('PATHS', repr(['frontend/static/js/app.js', 'frontend/static/css/app.css', 'frontend/static/js/api.js', 'frontend/static/js/questionnaires.js', 'backend/uv.lock']))
server = json.loads(subprocess.check_output(SSH + ['python3 -'], input=code.encode()))
assert all(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest for path, digest in server['source_hashes'].items())
result = dict(tls_verified=True, readiness=True, public_resources=resources, server=server)
(OUT / 'published.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
