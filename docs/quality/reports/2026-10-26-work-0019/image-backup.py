"""Approved WORK-0019: back up only the four named application image tags."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

OUT = Path(__file__).resolve().parent
PRIVATE = Path('/tmp/work0019-private')
PRIVATE.mkdir(mode=0o700, exist_ok=True)
TAGS = ['veganmedtech-server:' + x for x in ['20261024T235343Z-9097274c', '20261024T235815Z-6f6b551f', '20261025T100713Z-2af80812', '20261025T100946Z-da5a445c']]
KEYS = ('User', 'Env', 'Entrypoint', 'Cmd', 'WorkingDir', 'Labels', 'StopSignal', 'Healthcheck', 'ExposedPorts', 'Volumes')
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes', 'veganmedtech-server']


def identity(info):
    content = dict(rootfs=info['RootFS']['Layers'], os=info['Os'], architecture=info['Architecture'], config={k: info['Config'].get(k) for k in KEYS})
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


remote = json.loads(subprocess.check_output(SSH + ['python3 -'], input=('''import json,subprocess
tags=TAGS
infos=json.loads(subprocess.check_output(['docker','image','inspect',*tags]))
assert len({x['Id'] for x in infos})==1
assert set(infos[0]['RepoTags'])==set(tags)
assert not subprocess.check_output(['docker','ps','-aq','--filter','ancestor='+infos[0]['Id']]).strip()
for x in infos:
 for value in x['Config'].get('Env',[]):
  assert not value.startswith(('POLZA_API_KEY=','DJANGO_SECRET_KEY=','POSTGRES_PASSWORD=','SMTP_PASSWORD='))
print(json.dumps(infos))
'''.replace('TAGS', repr(TAGS))).encode()))
local = json.loads(subprocess.check_output(['docker', 'image', 'inspect', *TAGS]))
expected = identity(remote[0])
assert all(identity(x) == expected for x in remote + local), 'Local and remote application images differ'
archive = PRIVATE / 'work0014-application-image.tar.gz'
assert not archive.exists(), 'Do not overwrite an existing backup'
with archive.open('xb') as stream:
    saver = subprocess.Popen(['docker', 'image', 'save', *TAGS], stdout=subprocess.PIPE)
    with gzip.GzipFile(fileobj=stream, mode='wb', compresslevel=1, mtime=0) as compressed:
        for chunk in iter(lambda: saver.stdout.read(1024 * 1024), b''):
            compressed.write(chunk)
    assert saver.wait() == 0
archive.chmod(0o600)
with tarfile.open(archive, 'r:gz') as saved:
    manifest = json.load(saved.extractfile('manifest.json'))
    assert set(t for m in manifest for t in m['RepoTags']) == set(TAGS)
    for m in manifest:
        config = json.load(saved.extractfile(m['Config']))
        normalized = dict(RootFS={'Layers': config['rootfs']['diff_ids']}, Os=config['os'], Architecture=config['architecture'], Config=config['config'])
        assert identity(normalized) == expected
        for layer, diff_id in zip(m['Layers'], config['rootfs']['diff_ids']):
            digest = hashlib.sha256()
            with saved.extractfile(layer) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            assert 'sha256:' + digest.hexdigest() == diff_id
subprocess.run(['docker', 'image', 'load', '--input', str(archive)], check=True, stdout=subprocess.DEVNULL)
restored = json.loads(subprocess.check_output(['docker', 'image', 'inspect', *TAGS]))
assert all(identity(x) == expected for x in restored)
receipt = dict(tags=TAGS, remote_image_id=remote[0]['Id'], content_sha256=expected, archive_path=str(archive), archive_bytes=archive.stat().st_size,
               archive_sha256=hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest(), layers_verified=True, local_remote_identical=True,
               docker_load_passed=True, no_container_references=True, runtime_secret_variables_absent=True)
(OUT / 'image-backup.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
