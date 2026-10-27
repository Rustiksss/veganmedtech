"""Run on the server under explicit WORK-0020 r10 deployment approval."""
import argparse,hashlib,json,os,stat,fcntl
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--model',required=True);args=parser.parse_args()
assert args.model in {'cohere/command-r7b-12-2024'}, 'Only confirmed shortlist is allowed'
root=Path('/opt/veganmedtech');lock=os.open(root/'.deploy.lock',os.O_RDWR|os.O_NOFOLLOW);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
assert os.readlink(root/'current')=='releases/20261026T172503Z-368b0976'
p=root/'config/server.env';info=p.lstat();assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode)==0o600 and info.st_uid==0
raw=p.read_bytes();assert raw.endswith(b'\n')
lines=raw.decode().splitlines();values={}
for line in lines:
 k,v=line.split('=',1);assert k not in values;values[k]=v
baseline=json.loads((root/'backups/work0020-r10-preservation.json').read_text())
assert {k:hashlib.sha256(v.encode()).hexdigest() for k,v in values.items() if k!='POLZA_MODEL'}==baseline['config']
assert values.get('ASSISTANT_ALERTING_MODE')=='demo' and values['POLZA_MODEL']=='deepseek/deepseek-v4-flash'
backup=root/'backups/work0020-r10-before-model.env';fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
new=[('POLZA_MODEL='+args.model if line.startswith('POLZA_MODEL=') else line) for line in lines]
assert 'POLZA_MODEL' in values
tmp=p.with_name('server.work0020-r10-new');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'w') as f:f.write('\n'.join(new)+'\n');f.flush();os.fsync(f.fileno())
tmp.replace(p)
after=dict(line.split('=',1) for line in p.read_text().splitlines())
assert {k:v for k,v in after.items() if k!='POLZA_MODEL'}=={k:v for k,v in values.items() if k!='POLZA_MODEL'}
assert stat.S_IMODE(p.stat().st_mode)==0o600
print(json.dumps({'mode':'demo','model':args.model,'other_values_preserved':True,'permissions':'0600','private_backup_created':True}))
