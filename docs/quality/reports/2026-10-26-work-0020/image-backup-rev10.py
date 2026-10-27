"""WORK-0020 r10: verify recoverable archive of exactly the old WORK-0019 image."""
import gzip,hashlib,json,subprocess,tarfile,shlex
from pathlib import Path
OUT=Path(__file__).resolve().parent;PRIVATE=Path('/tmp/work0020-private');PRIVATE.mkdir(mode=0o700,exist_ok=True)
TAGS=['veganmedtech-server:20261026T001026Z-fb8cfa65','veganmedtech-server:20261026T002622Z-7fc599bf']
KEYS=('User','Env','Entrypoint','Cmd','WorkingDir','Labels','StopSignal','Healthcheck','ExposedPorts','Volumes')
SSH=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no','-o','ClearAllForwardings=yes','veganmedtech-server']
def identity(info):
 d=dict(rootfs=info['RootFS']['Layers'],os=info['Os'],architecture=info['Architecture'],config={k:info['Config'].get(k) for k in KEYS})
 return hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':')).encode()).hexdigest()
remote_code='''import hashlib,json,os,subprocess
from pathlib import Path
tags=TAGS;keys=KEYS
images=json.loads(subprocess.check_output(['docker','image','inspect',*tags]));assert len({i['Id'] for i in images})==1
i=images[0];assert i['Id']=='sha256:c866c83347250a411451cd9d730b4339471ce91d3fa8b5b2a9e0a960880f0ac0'
assert set(i['RepoTags'])==set(tags)
assert not subprocess.check_output(['docker','ps','-aq','--filter','ancestor='+i['Id']]).strip()
assert os.readlink('/opt/veganmedtech/current')=='releases/20261026T172503Z-368b0976'
assert os.readlink('/opt/veganmedtech/previous')=='releases/20261026T171831Z-b0771a9e'
assert not any(v.startswith(('POLZA_API_KEY=','DJANGO_SECRET_KEY=','POSTGRES_PASSWORD=','SMTP_PASSWORD=')) for v in i['Config'].get('Env',[]))
d=dict(rootfs=i['RootFS']['Layers'],os=i['Os'],architecture=i['Architecture'],config={k:i['Config'].get(k) for k in keys})
print(json.dumps({'id':i['Id'],'identity':hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'layers':i['RootFS']['Layers']}))
'''.replace('TAGS',repr(TAGS)).replace('KEYS',repr(KEYS))
remote=json.loads(subprocess.check_output(SSH+['python3 -'],input=remote_code.encode()))
found=subprocess.run(['docker','image','inspect',*TAGS],capture_output=True,text=True)
local=json.loads(found.stdout) if found.returncode==0 else None
if local is not None:assert all(identity(i)==remote['identity'] for i in local)
archive=PRIVATE/'work0019-previous-r10-image.tar.gz';assert not archive.exists()
with archive.open('xb') as f:
 save_command=['docker','image','save',*TAGS] if local is not None else SSH+['docker image save '+shlex.join(TAGS)]
 saver=subprocess.Popen(save_command,stdout=subprocess.PIPE)
 with gzip.GzipFile(fileobj=f,mode='wb',compresslevel=1,mtime=0) as zipped:
  for chunk in iter(lambda:saver.stdout.read(1024*1024),b''):zipped.write(chunk)
 assert saver.wait()==0
archive.chmod(0o600)
with tarfile.open(archive,'r:gz') as saved:
 manifests=json.load(saved.extractfile('manifest.json'));assert set(t for m in manifests for t in m['RepoTags'])==set(TAGS)
 for m in manifests:
  c=json.load(saved.extractfile(m['Config']));normalized=dict(RootFS={'Layers':c['rootfs']['diff_ids']},Os=c['os'],Architecture=c['architecture'],Config=c['config'])
  assert identity(normalized)==remote['identity']
  for path,diff in zip(m['Layers'],c['rootfs']['diff_ids']):
   with saved.extractfile(path) as f:assert 'sha256:'+hashlib.file_digest(f,'sha256').hexdigest()==diff
subprocess.run(['docker','image','load','--input',str(archive)],check=True,stdout=subprocess.DEVNULL)
assert all(identity(i)==remote['identity'] for i in json.loads(subprocess.check_output(['docker','image','inspect',*TAGS])))
with archive.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
receipt={'archive_source':'verified local image' if local is not None else 'direct remote Docker save stream; no remote archive', 'tags':TAGS,'remote_image_id':remote['id'],'content_sha256':remote['identity'],'archive_path':str(archive),'archive_bytes':archive.stat().st_size,'archive_sha256':sha,'layers_verified':True,'docker_load_passed':True,'local_remote_identical':True,'runtime_secret_variables_absent':True,'no_container_references':True}
(OUT/'image-backup-rev10.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
