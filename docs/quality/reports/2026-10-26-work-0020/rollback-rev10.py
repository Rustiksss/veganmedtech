"""Emergency application/config rollback only; run on the host with exact current ID."""
import argparse,fcntl,json,os,re,stat,subprocess,urllib.request
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--from-release',required=True);args=p.parse_args()
assert re.fullmatch(r'202610[0-9]{2}T[0-9]{6}Z-[a-f0-9]{8}',args.from_release)
root=Path('/opt/veganmedtech');target='20261026T172503Z-368b0976'
fd=os.open(root/'.deploy.lock',os.O_RDWR|os.O_NOFOLLOW);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
assert os.readlink(root/'current')=='releases/'+args.from_release
assert (root/'releases'/target).is_dir()
backup=root/'backups/work0020-r10-before-model.env';assert stat.S_IMODE(backup.stat().st_mode)==0o600
raw=backup.read_bytes();values=dict(line.split('=',1) for line in raw.decode().splitlines())
assert values['POLZA_MODEL']=='deepseek/deepseek-v4-flash' and values['ASSISTANT_ALERTING_MODE']=='demo'
temporary=root/'config/server.work0020-r10-rollback'
x=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(x,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
temporary.replace(root/'config/server.env')
release=root/'releases'/target
environment={'PATH':os.environ['PATH'],'DEPLOY_IMAGE':'veganmedtech-server:'+target}
subprocess.run(['docker','compose','--project-directory',str(release),'-p','veganmedtech','--env-file',str(root/'config/server.env'),'-f',str(release/'compose.yaml'),'-f',str(release/'compose.deploy.yaml'),'--profile','dev','up','-d','--no-build','--wait','--wait-timeout','180','app'],env=environment,check=True)
with urllib.request.urlopen('https://94.103.3.149/health/ready',timeout=10) as r:assert json.load(r)['ready'] is True
if args.from_release!=target:
 for name,value in [('previous','releases/'+args.from_release),('current','releases/'+target)]:
  temp=root/('.'+name+'-r10-rollback');assert not temp.exists() and not temp.is_symlink();temp.symlink_to(value);temp.replace(root/name)
print(json.dumps({'r4_application_and_private_config_restored':True,'database_replaced':False,'public_ready':True}))
