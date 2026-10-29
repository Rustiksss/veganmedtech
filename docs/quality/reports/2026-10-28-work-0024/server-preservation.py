"""Run on the deployment host; only counts and boolean checks leave that host."""
import hashlib,json,os,subprocess,sys,urllib.request
from pathlib import Path
ROOT=Path('/opt/veganmedtech');BASELINE=ROOT/'backups/work0024-preservation.json'
TABLES=['accounts_user','care_carerelationship','reports_selfreport','assistant_assistantturn','assistant_assistantattempt','assistant_assistantnotification','audit_auditevent']
mode=sys.argv[1]
before=json.loads(BASELINE.read_text()) if mode!='capture' else None
columns={t:info['columns'] for t,info in before['tables'].items()} if before else None
code='''import json
from django.db import connection
tables=TABLES
columns=COLUMNS
result={}
with connection.cursor() as cur:
 for table in tables:
  if columns is None:
   cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",[table])
   selected=[r[0] for r in cur.fetchall()]
  else:selected=columns[table]
  q=connection.ops.quote_name
  cur.execute('SELECT id,md5(row_to_json(t)::text) FROM (SELECT '+','.join(q(c) for c in selected)+' FROM '+q(table)+') t ORDER BY id')
  result[table]={'columns':selected,'rows':{str(pk):digest for pk,digest in cur.fetchall()}}
print('PRESERVATION_JSON:'+json.dumps(result))
'''.replace('TABLES',repr(TABLES)).replace('COLUMNS',repr(columns))
raw=subprocess.check_output(['docker','exec','-i','veganmedtech-app-1','python','manage.py','shell'],input=code.encode()).decode()
tables=json.loads(next(line.split('PRESERVATION_JSON:',1)[1] for line in raw.splitlines() if line.startswith('PRESERVATION_JSON:')))
values=dict(line.split('=',1) for line in (ROOT/'config/server.env').read_text().splitlines())
config={k:hashlib.sha256(v.encode()).hexdigest() for k,v in values.items()}
files=[ROOT/'config/mailpit-access.json',Path('/etc/veganmedtech/proxy.env'),Path('/etc/veganmedtech/Caddyfile')]
files += [p for p in Path('/var/lib/veganmedtech-caddy/production').rglob('*') if p.is_file() and p.suffix in {'.crt','.key'}]
hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
with urllib.request.urlopen('http://127.0.0.1:18025/api/v1/messages?limit=1000',timeout=10) as r:mail=json.load(r)
assert mail.get('total',len(mail['messages']))<=1000
now={'tables':tables,'config':config,'files':hashes,'mail_ids':sorted(m['ID'] for m in mail['messages']),
     'mailpit_id':subprocess.check_output(['docker','inspect','--format','{{.Id}}','veganmedtech-mailpit-1'],text=True).strip(),
     'links':{k:os.readlink(ROOT/k) for k in ['current','previous']},'mode':values.get('ASSISTANT_ALERTING_MODE','off')}
if mode=='capture':
 fd=os.open(BASELINE,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:json.dump(now,f)
 print(json.dumps({'captured':True,'counts':{t:len(v['rows']) for t,v in tables.items()},'mail_count':len(now['mail_ids']),'links':now['links'],'mode':now['mode']}))
else:
 checks={'original_columns_and_rows_preserved':all(all(tables[t]['rows'].get(pk)==digest for pk,digest in info['rows'].items()) for t,info in before['tables'].items()),
         'other_config_values_preserved':before['config']==now['config'],'tls_proxy_operator_preserved':before['files']==now['files'],
         'old_mail_retained':set(before['mail_ids'])<=set(now['mail_ids']),'mailpit_container_preserved':before['mailpit_id']==now['mailpit_id'],
         'alerting_mode_preserved':now['mode']==before['mode']}
 print(json.dumps({'checks':checks,'counts':{t:len(v['rows']) for t,v in tables.items()},'mail_count':len(now['mail_ids']),'links':now['links'],'available_bytes':os.statvfs('/opt').f_bavail*os.statvfs('/opt').f_frsize}))
 assert all(checks.values()),'Preservation mismatch; no data overwritten'
