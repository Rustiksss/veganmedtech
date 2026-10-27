"""Destructive checks only against the isolated WORK-0008 synthetic Compose project."""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import subprocess
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--env-file',required=True)
    parser.add_argument('--project',default='veganmedtech-work0008-test')
    parser.add_argument('--base-url',default='http://localhost:18008')
    parser.add_argument('--output',default='/tmp/work0008-container-results.json')
    args=parser.parse_args()
    if args.project!='veganmedtech-work0008-test':raise SystemExit('Only the isolated WORK-0008 test project is permitted')
    command=['docker','compose','--env-file',args.env_file,'-p',args.project,'--profile','dev']
    checks=[]
    def run(*parts,input=None,env=None):
        return subprocess.run(command+list(parts),cwd=ROOT,input=input,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,env=env).stdout.decode()
    def check(name,value):
        checks.append({'name':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    def shell(code):return run('exec','-T','app','python','manage.py','shell','-c',code)
    private=Path('/tmp/work0008-ops-private.json')
    if not private.exists():
        private.write_text(json.dumps({'password':secrets.token_urlsafe(24)}));private.chmod(0o600)
    password=json.loads(private.read_text())['password']
    env=dict(os.environ,DEMO_PASSWORD=password)
    run('exec','-T','-e','DEMO_PASSWORD','app','python','manage.py','seed_demo',env=env)
    before=shell('from accounts.models import User; print(User.objects.count())').splitlines()[-1]
    run('exec','-T','-e','DEMO_PASSWORD','app','python','manage.py','seed_demo',env=env)
    check('seed repeat preserves users',shell('from accounts.models import User; print(User.objects.count())').splitlines()[-1]==before)
    class Client:
        def __init__(self):
            self.cookies=http.cookiejar.CookieJar()
            self.open=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        def request(self,path,method='GET',body=None,headers=None):
            heads={'Accept':'application/json',**(headers or {})}
            if method!='GET':
                heads['X-CSRFToken']=next((c.value for c in self.cookies if c.name=='csrftoken'),'')
            payload=None
            if body is not None:payload=json.dumps(body).encode();heads['Content-Type']='application/json'
            req=urllib.request.Request(args.base_url+path,payload,headers=heads,method=method)
            try:r=self.open.open(req,timeout=15)
            except urllib.error.HTTPError as e:r=e
            data=r.read()
            return r.status,data,dict(r.headers)
        def login(self,pw):
            self.request('/')
            return self.request('/_allauth/browser/v1/auth/login','POST',{'email':'patient-a@example.test','password':pw})
    c=Client();check('normal seeded login works',c.login(password)[0]==200)
    body={'observed_at':'2026-10-20T12:00:00Z','text':'SYNTHETIC_CONTAINER_MARKER_0008'}
    status,data,_=c.request('/api/me/self-reports','POST',body,{'Idempotency-Key':'container-persistence'})
    check('persistent record exists',status in [200,201]);record=json.loads(data)
    check('https configuration has secure cookies',run('run','--rm','-e','APP_DEV_MODE=0','-e','APP_BASE_URL=https://localhost','app','python','-c',"import os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');import django;django.setup();from django.conf import settings;from django.test import Client;assert settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE;assert Client().get('/',secure=True,HTTP_HOST='localhost').cookies['csrftoken']['secure'];print('ok')").strip()=='ok')
    check('runtime uid is unprivileged',run('exec','-T','app','id','-u').strip()=='10001')
    run('exec','-T','app','python','manage.py','makemigrations','--check','--dry-run')
    check('schema matches migrations',True)
    status,html,_=Client().request('/')
    check('html shell without user records',status==200 and b'SYNTHETIC_CONTAINER_MARKER' not in html)
    import re
    assets=re.findall(rb'(?:href|src)="(/static/[^"]+)"',html)
    check('three scripts and stylesheet are served',len(assets)==4 and all(Client().request(x.decode())[0]==200 for x in assets))
    check('image excludes repository private and source materials',run('exec','-T','app','python','-c',"from pathlib import Path; assert all(not (Path('/app')/p).exists() for p in ['.env','.git','.codex','.aws','.agents','docs','misc_materials','tests']);print('ok')").strip()=='ok')
    run('stop','db')
    try:
        check('readiness fails with database offline',Client().request('/health/ready')[0]==503)
        check('database failure never returns empty success',c.request('/api/me/self-reports')[0]==503)
    finally:run('up','-d','--wait','db')
    check('ready after database recovery',Client().request('/health/ready')[0]==200)
    run('restart','app');run('up','-d','--wait','app')
    check('session survives process restart',c.request('/api/me')[0]==200)
    check('idempotency survives restart',c.request('/api/me/self-reports','POST',body,{'Idempotency-Key':'container-persistence'})[:2]==(200,data))
    run('up','-d','--force-recreate','--wait')
    check('account and session survive container recreation',c.request('/api/me')[0]==200)
    check('record survives container recreation',json.loads(c.request('/api/me/self-reports')[1])['results'][0]['id']==record['id'])
    sql="SELECT json_build_object('users',(SELECT count(*) FROM accounts_user),'links',(SELECT count(*) FROM care_carerelationship),'reports',(SELECT count(*) FROM reports_selfreport),'audit',(SELECT count(*) FROM audit_auditevent));"
    def counts(database):return json.loads(run('exec','-T','db','sh','-c','psql -At -U "$POSTGRES_USER" "$1" -c "$2"','sh',database,sql).strip())
    expected=counts('compass')
    dump=run('exec','-T','db','sh','-c','pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"')
    backup=Path('/tmp/work0008-synthetic.sql');backup.write_text(dump);backup.chmod(0o600)
    restore='compass_restore_'+secrets.token_hex(4)
    run('exec','-T','db','sh','-c','createdb -U "$POSTGRES_USER" "$1"','sh',restore)
    run('exec','-T','db','sh','-c','psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$1"','sh',restore,input=dump.encode())
    check('backup restores users links reports and audit',counts(restore)==expected)
    # Prove rate-limit state is shared by *different* Gunicorn workers.
    workers=json.loads(run('exec','-T','app','python','-c',"from pathlib import Path; import json;print(json.dumps([int(p) for p in Path('/proc/1/task/1/children').read_text().split()]))"))
    check('gunicorn has two workers',len(workers)==2)
    def signal(pid,name):run('exec','-T','app','python','-c',f'import os,signal;os.kill({pid},signal.SIG{name})')
    # Only own synthetic counters are cleared; this script refuses every other project.
    shell('from django.core.cache import cache;cache.clear()')
    try:
        signal(workers[1],'STOP')
        for _ in range(5):check('wrong password rejected',Client().login('synthetic-wrong-password')[0]==400)
        signal(workers[1],'CONT');signal(workers[0],'STOP')
        check('another worker enforces same login limit',Client().login(password)[0] in [400,429])
    finally:
        for pid in workers:
            try:signal(pid,'CONT')
            except subprocess.CalledProcessError:pass
    run('restart','app');run('up','-d','--wait','app')
    check('login limit survives application restart',Client().login(password)[0] in [400,429])
    logs=run('logs','--no-color','app')
    check('ordinary logs exclude report and credentials',body['text'] not in logs and password not in logs and 'csrftoken=' not in logs and 'sessionid=' not in logs)
    result={'passed':sum(x['passed'] for x in checks),'failed':sum(not x['passed'] for x in checks),'checks':checks,'restored_counts':expected}
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':result['passed'],'failed':result['failed'],'restore':expected}))

if __name__=='__main__':main()
