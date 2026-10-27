"""Compare published runtime with local sources; never emit environment values."""
import hashlib,json,subprocess,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
names=['backend/assistant/'+n for n in ['client.py','alerting.py','models.py','services.py','views.py','prompts.py','alert_policy.demo.json','alert_policy.template.json','migrations/0002_demo_analysis.py','migrations/0003_rollback_defaults.py']]
names+=['backend/config/settings.py','backend/pyproject.toml','backend/uv.lock','frontend/static/js/app.js','frontend/static/js/api.js','frontend/static/js/questionnaires.js','frontend/static/css/app.css']
expected={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}
inner='''import hashlib,json,os
from pathlib import Path
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.conf import settings
from django.db.migrations.recorder import MigrationRecorder
from assistant.alerting import mode_output
expected=EXPECTED
key=os.environ.get('POLZA_API_KEY','').encode()
checks={'source_hashes_match':all(hashlib.sha256((Path('/app')/n).read_bytes()).hexdigest()==v for n,v in expected.items()),
 'mode_demo_clinical_disabled':mode_output()=={'alerting_mode':'demo','demo_detection_enabled':True,'automatic_detection_enabled':False},
 'polza_configured':bool(key),'model_unchanged':settings.POLZA_MODEL=='deepseek/deepseek-v4-flash',
 'migrations_applied':all(MigrationRecorder.Migration.objects.filter(app='assistant',name=n).exists() for n in ['0002_demo_analysis','0003_rollback_defaults']),
 'test_upstream_absent':not Path('/app/backend/demo_wsgi.py').exists()}
checks['key_absent_from_sources_and_static']=bool(key) and Path(settings.STATIC_ROOT).is_dir() and not any(key in p.read_bytes() for root in ['/app/frontend',str(settings.STATIC_ROOT)] for p in Path(root).rglob('*') if p.is_file())
print(json.dumps({'checks':checks,'source_sha256':expected}))
assert all(checks.values())
'''.replace('EXPECTED',repr(expected))
outer='''import json,os,stat,subprocess,urllib.request
from pathlib import Path
root=Path('/opt/veganmedtech')
result=json.loads(subprocess.check_output(['docker','exec','-i','veganmedtech-app-1','python','-c',INNER],text=True))
result['checks']['env_private_0600']=stat.S_IMODE((root/'config/server.env').stat().st_mode)==0o600
result['checks']['work0019_image_retained']=subprocess.run(['docker','image','inspect','veganmedtech-server:20261026T002622Z-7fc599bf'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
result['checks']['temporary_apt_window_released']=not (root/'backups/work0020-apt-window.pid').exists() and not (root/'backups/work0020-apt-window.stop').exists()
result['containers']={n:subprocess.check_output(['docker','inspect','--format','{{.State.Health.Status}}' if n!='veganmedtech-mailpit-1' else '{{.State.Running}}',n],text=True).strip() for n in ['veganmedtech-app-1','veganmedtech-db-1','veganmedtech-mailpit-1']}
result['checks']['containers_healthy']=result['containers']=={'veganmedtech-app-1':'healthy','veganmedtech-db-1':'healthy','veganmedtech-mailpit-1':'true'}
result['links']={n:os.readlink(root/n) for n in ['current','previous']}
result['image']=subprocess.check_output(['docker','inspect','--format','{{.Image}}','veganmedtech-app-1'],text=True).strip()
result['available_bytes']=os.statvfs('/opt').f_bavail*os.statvfs('/opt').f_frsize
result['checks']['reserve_256mib']=result['available_bytes']>=268435456
print(json.dumps(result))
assert all(result['checks'].values())
'''.replace('INNER',repr(inner))
ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no','-o','ClearAllForwardings=yes','veganmedtech-server','python3 -']
data=json.loads(subprocess.check_output(ssh,input=outer.encode()))
public={}
for name in ['frontend/static/js/app.js','frontend/static/js/api.js','frontend/static/css/app.css']:
    with urllib.request.urlopen('https://94.103.3.149/static/'+name.split('/static/')[1],timeout=10) as r:public[name]=hashlib.sha256(r.read()).hexdigest()==expected[name]
data['public_assets_match']=public
assert all(public.values())
Path(__file__).with_name('runtime.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'runtime_checks':len(data['checks']),'public_assets':len(public),'passed':True}))
