"""Only the exact four tags authorized in WORK-0019, after a verified backup."""
import hashlib
import json
from pathlib import Path
import subprocess

OUT = Path(__file__).resolve().parent
receipt = json.loads((OUT / 'image-backup.json').read_text())
archive = Path(receipt['archive_path'])
assert receipt['docker_load_passed'] and receipt['layers_verified'] and receipt['local_remote_identical']
with archive.open('rb') as stream:
    assert hashlib.file_digest(stream, 'sha256').hexdigest() == receipt['archive_sha256']
ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes', 'veganmedtech-server']
code = '''import fcntl,hashlib,json,os,subprocess
from pathlib import Path
r=RECEIPT
root=Path('/opt/veganmedtech')
fd=os.open(root/'.deploy.lock',os.O_RDWR|os.O_NOFOLLOW)
fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
expected={'current':'releases/20261025T213505Z-81b7c2d9','previous':'releases/20261025T212653Z-8ecec0d6'}
assert {k:os.readlink(root/k) for k in expected}==expected
infos=json.loads(subprocess.check_output(['docker','image','inspect',*r['tags']]))
assert len({x['Id'] for x in infos})==1 and infos[0]['Id']==r['remote_image_id']
info=infos[0]
assert set(info['RepoTags'])==set(r['tags'])
keys=('User','Env','Entrypoint','Cmd','WorkingDir','Labels','StopSignal','Healthcheck','ExposedPorts','Volumes')
content=dict(rootfs=info['RootFS']['Layers'],os=info['Os'],architecture=info['Architecture'],config={k:info['Config'].get(k) for k in keys})
assert hashlib.sha256(json.dumps(content,sort_keys=True,separators=(',',':')).encode()).hexdigest()==r['content_sha256']
assert not subprocess.check_output(['docker','ps','-aq','--filter','ancestor='+info['Id']]).strip()
for target in expected.values():
 manifest=json.loads((root/target/'image.json').read_text())
 assert manifest['image_tag'] not in r['tags']
def tags():return set(subprocess.check_output(['docker','image','ls','--format','{{.Repository}}:{{.Tag}}','veganmedtech-server'],text=True).splitlines())
before=tags();free_before=os.statvfs('/opt').f_bavail*os.statvfs('/opt').f_frsize
subprocess.run(['docker','image','rm',*r['tags']],check=True,stdout=subprocess.DEVNULL)
after=tags()
assert before-after==set(r['tags']) and not after-before
assert {k:os.readlink(root/k) for k in expected}==expected
health={name:subprocess.check_output(['docker','inspect','--format','{{.State.Health.Status}}',name],text=True).strip() for name in ['veganmedtech-app-1','veganmedtech-db-1','veganmedtech-mailpit-1']}
assert all(value=='healthy' for value in health.values())
free_after=os.statvfs('/opt').f_bavail*os.statvfs('/opt').f_frsize
assert free_after>=268435456
print(json.dumps(dict(removed_tags=sorted(before-after),remaining_tags=sorted(after),current_previous_preserved=True,health=health,available_before=free_before,available_after=free_after,freed_bytes=free_after-free_before)))
'''.replace('RECEIPT', repr({k: receipt[k] for k in ['tags', 'remote_image_id', 'content_sha256']}))
result = subprocess.check_output(ssh + ['python3 -'], input=code.encode())
data = json.loads(result)
(OUT / 'cleanup.json').write_text(json.dumps(data, indent=2) + '\n')
print(json.dumps(data, indent=2))
