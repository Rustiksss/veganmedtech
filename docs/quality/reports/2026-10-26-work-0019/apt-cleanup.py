"""One approved WORK-0019 rev2 cleanup of exactly the inventoried cache files."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

manifest = json.load(sys.stdin)
assert len(manifest['files']) == 172
ROOT = Path('/opt/veganmedtech')
REPORT = ROOT / 'backups/work0019-apt-cleanup.json'
assert not REPORT.exists() and not REPORT.is_symlink(), 'One-time cleanup already recorded'
allowed_parents = {Path('/var/lib/apt/lists'), Path('/var/cache/apt/archives'), Path('/var/cache/apt/archives/partial')}
binary_caches = {Path('/var/cache/apt/pkgcache.bin'), Path('/var/cache/apt/srcpkgcache.bin')}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def state():
    paths = [Path('/var/lib/dpkg/status')]
    paths += [p for folder in ['/etc/apt', '/etc/systemd/system'] for p in Path(folder).rglob('*') if p.is_file() and not p.is_symlink()]
    paths += [Path('/usr/lib/systemd/system') / name for name in ['apt-daily.service', 'apt-daily.timer', 'apt-daily-upgrade.service', 'apt-daily-upgrade.timer']]
    return dict(files={str(p): digest(p) for p in paths},
                timers={name: subprocess.check_output(['systemctl', 'is-enabled', name], text=True).strip() for name in ['apt-daily.timer', 'apt-daily-upgrade.timer']})


with contextlib.ExitStack() as stack:
    locks = ['/var/lib/dpkg/lock-frontend', '/var/lib/dpkg/lock', '/var/lib/apt/lists/lock', '/var/cache/apt/archives/lock']
    for name in locks:
        descriptor = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
        stream = stack.enter_context(os.fdopen(descriptor, 'r+'))
        fcntl.lockf(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    for name in ['apt-daily.service', 'apt-daily-upgrade.service']:
        status = subprocess.run(['systemctl', 'is-active', name], capture_output=True, text=True).stdout.strip()
        assert status in {'inactive', 'failed'}, 'APT is active; no files removed'
    seen = set()
    # Validate every file before deleting any, including the exact inode/version.
    for entry in manifest['files']:
        p = Path(entry['path'])
        assert p not in seen and p.name != 'lock'
        seen.add(p)
        assert p in binary_caches or p.parent in allowed_parents
        assert p.parent != Path('/var/cache/apt/archives') or p.suffix == '.deb'
        assert not p.parent.is_symlink() and not p.is_symlink()
        info = p.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_uid == entry['uid'] == 0
        assert (info.st_ino, info.st_size, info.st_mtime_ns) == (entry['inode'], entry['bytes'], entry['mtime_ns']), str(p)
    before = state()
    assert all(value == 'enabled' for value in before['timers'].values())
    free_before = os.statvfs('/opt').f_bavail * os.statvfs('/opt').f_frsize
    for entry in manifest['files']:
        p = Path(entry['path'])
        info = p.lstat()
        assert (info.st_ino, info.st_size, info.st_mtime_ns) == (entry['inode'], entry['bytes'], entry['mtime_ns'])
        p.unlink()
    after = state()
    assert after == before, 'Installed package database or update configuration changed'
    available = os.statvfs('/opt').f_bavail * os.statvfs('/opt').f_frsize
    health = {name: subprocess.check_output(['docker', 'inspect', '--format', '{{.State.Health.Status}}', name], text=True).strip() for name in ['veganmedtech-app-1', 'veganmedtech-db-1', 'veganmedtech-mailpit-1']}
    result = dict(task='WORK-0019', approved_revision=2, files_removed=len(manifest['files']), removed_files=manifest['files'],
                  allocated_removed=sum(x['allocated_bytes'] for x in manifest['files']), available_before=free_before, available_after=available,
                  locks_held=locks, packages_and_configuration_unchanged=after == before, timers=after['timers'], health=health)
    descriptor = os.open(REPORT, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))
    assert available >= 268435456 and all(v == 'healthy' for v in health.values()), 'Reserve/health not satisfied; no further cleanup authorized'
