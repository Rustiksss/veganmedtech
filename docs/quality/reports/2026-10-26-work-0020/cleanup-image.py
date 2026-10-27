"""Remove exactly the two old previous tags only after the verified local archive."""
import hashlib,json,subprocess
from pathlib import Path
OUT=Path(__file__).resolve().parent;r=json.loads((OUT/'image-backup.json').read_text())
assert all(r[k] for k in ['layers_verified','docker_load_passed','local_remote_identical','no_container_references','runtime_secret_variables_absent'])
with Path(r['archive_path']).open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==r['archive_sha256']
code='''import fcntl,hashlib,json,os,subprocess
from pathlib import Path
r=RECEIPT;root=Path('/opt/veganmedtech');fd=os.open(root/'.deploy.lock',os.O_RDWR|os.O_NOFOLLOW);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
expected={'current':'releases/20261026T002622Z-7fc599bf','previous':'releases/20261025T213505Z-81b7c2d9'}
assert {k:os.readlink(root/k) for k in expected}==expected
infos=json.loads(subprocess.check_output(['docker','image','inspect',*r['tags']]));assert len({i['Id'] for i in infos})==1
info=infos[0];assert info['Id']==r['remote_image_id'] and set(info['RepoTags'])==set(r['tags'])
assert not subprocess.check_output(['docker','ps','-aq','--filter','ancestor='+info['Id']]).strip()
keys=('User','Env','Entrypoint','Cmd','WorkingDir','Labels','StopSignal','Healthcheck','ExposedPorts','Volumes')
d=dict(rootfs=info['RootFS']['Layers'],os=info['Os'],architecture=info['Architecture'],config={k:info['Config'].get(k) for k in keys})
assert hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':')).encode()).hexdigest()==r['content_sha256']
def tags():return set(subprocess.check_output(['docker','image','ls','--format','{{.Repository}}:{{.Tag}}','veganmedtech-server'],text=True).splitlines())
before=tags();free_before=os.statvfs('/opt').f_bavail*os.statvfs('/opt').f_frsize
subprocess.run(['docker','image','rm',*r['tags']],check=True,stdout=subprocess.DEVNULL)
after=tags();assert before-after==set(r['tags']) and not after-before
assert {k:os.readlink(root/k) for k in expected}==expected
health={name:subprocess.check_output(['docker','inspect','--format','{{.State.Health.Status}}',name],text=True).strip() for name in ['veganmedtech-app-1','veganmedtech-db-1','veganmedtech-mailpit-1']}
assert all(x=='healthy' for x in health.values())
free_after=os.statvfs('/opt').f_bavail*os.statvfs('/opt').f_frsize;assert free_after>=268435456
print(json.dumps({'removed_tags':sorted(before-after),'remaining_tags':sorted(after),'available_before':free_before,'available_after':free_after,'freed_bytes':free_after-free_before,'current_preserved':True,'health':health}))
'''.replace('RECEIPT',repr({k:r[k] for k in ['tags','remote_image_id','content_sha256']}))
ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no','-o','ClearAllForwardings=yes','veganmedtech-server']
data=json.loads(subprocess.check_output(ssh+['python3 -'],input=code.encode()))
(OUT/'cleanup.json').write_text(json.dumps(data,indent=2)+'\n');print(json.dumps(data))
