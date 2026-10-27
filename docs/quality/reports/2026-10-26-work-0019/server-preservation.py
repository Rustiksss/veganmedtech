"""Run on the deployment host. Private fingerprints stay on that host."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path('/opt/veganmedtech')
BASELINE = ROOT / 'backups/work0019-preservation.json'


def snapshot():
    files = [ROOT / 'config/server.env', ROOT / 'config/mailpit-access.json', Path('/etc/veganmedtech/proxy.env')]
    tls = Path('/var/lib/veganmedtech-caddy/production')
    files += [p for p in tls.rglob('*') if p.is_file() and p.suffix in {'.crt', '.key'}]
    config = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    code = '''import json
from django.db import connection
tables=['accounts_user','care_carerelationship','reports_selfreport','assistant_assistantturn','assistant_assistantattempt','assistant_assistantnotification','audit_auditevent']
rows={}
with connection.cursor() as cur:
 for table in tables:
  cur.execute('SELECT id, md5(row_to_json(t)::text) FROM '+connection.ops.quote_name(table)+' AS t ORDER BY id')
  rows[table]={str(pk):digest for pk,digest in cur.fetchall()}
print('PRESERVATION_JSON:'+json.dumps(rows))
'''
    output = subprocess.check_output(['docker', 'exec', '-i', 'veganmedtech-app-1', 'python', 'manage.py', 'shell'], input=code.encode()).decode()
    rows = json.loads(next(line.split('PRESERVATION_JSON:', 1)[1] for line in output.splitlines() if 'PRESERVATION_JSON:' in line))
    with urllib.request.urlopen('http://127.0.0.1:18025/api/v1/messages?limit=1000', timeout=10) as response:
        mail = json.load(response)
    return dict(files=config, rows=rows, mail_ids=sorted(x['ID'] for x in mail['messages']),
                mailpit_id=subprocess.check_output(['docker', 'inspect', '--format', '{{.Id}}', 'veganmedtech-mailpit-1'], text=True).strip(),
                links={x: os.readlink(ROOT / x) for x in ['current', 'previous']})


now = snapshot()
if sys.argv[1] == 'capture':
    descriptor = os.open(BASELINE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(now, stream)
    print(json.dumps(dict(captured=True, private_baseline=str(BASELINE), counts={k: len(v) for k, v in now['rows'].items()}, mail_count=len(now['mail_ids']), links=now['links'])))
else:
    before = json.loads(BASELINE.read_text())
    checks = dict(config_and_tls_preserved=all(now['files'].get(k) == v for k, v in before['files'].items()),
                  baseline_rows_preserved=all(all(now['rows'][t].get(k) == v for k, v in rows.items()) for t, rows in before['rows'].items()),
                  mailpit_container_preserved=now['mailpit_id'] == before['mailpit_id'],
                  baseline_mail_retained=set(before['mail_ids']) <= set(now['mail_ids']))
    result = dict(checks=checks, counts={k: len(v) for k, v in now['rows'].items()}, links=now['links'],
                  available_bytes=os.statvfs('/opt').f_bavail * os.statvfs('/opt').f_frsize)
    print(json.dumps(result))
    assert all(checks.values()), 'Preservation mismatch; no data is overwritten'
