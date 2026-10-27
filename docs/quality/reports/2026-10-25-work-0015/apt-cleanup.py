"""One approved WORK-0015 rev2 maintenance operation; no package/config mutations."""
import contextlib,fcntl,json,os,shutil,stat,subprocess
from pathlib import Path
root=Path('/opt/veganmedtech')
report=root/'backups/work0015-apt-cleanup.json'
assert not report.exists() and not report.is_symlink(),'This one-time operation already has a record'
lock_names=['/var/lib/dpkg/lock-frontend','/var/lib/dpkg/lock','/var/lib/apt/lists/lock','/var/cache/apt/archives/lock']
with contextlib.ExitStack() as stack:
 for name in lock_names:
  fd=os.open(name,os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC)
  stream=stack.enter_context(os.fdopen(fd,'r+'))
  fcntl.lockf(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
 for name in ['apt-daily.service','apt-daily-upgrade.service']:
  result=subprocess.run(['systemctl','is-active',name],capture_output=True,text=True)
  assert result.stdout.strip() in ['inactive','failed','unknown'], 'APT operation active; no files removed'
 folders=[Path('/var/lib/apt/lists'),Path('/var/cache/apt/archives')]
 assert all(p.is_dir() and not p.is_symlink() for p in folders)
 paths=[Path('/var/cache/apt/pkgcache.bin'),Path('/var/cache/apt/srcpkgcache.bin')]
 paths+=list(folders[0].iterdir());paths+=list(folders[1].glob('*.deb'))
 files=[]
 for p in sorted(paths):
  if not p.exists() and not p.is_symlink():continue
  info=p.lstat()
  if p.name!='lock' and stat.S_ISREG(info.st_mode):
   assert info.st_uid==0
   files.append(dict(path=str(p),size=info.st_size,allocated=info.st_blocks*512,inode=info.st_ino,mtime_ns=info.st_mtime_ns))
 record=dict(task='WORK-0015',approved_revision=2,status='in_progress',free_before=shutil.disk_usage(root).free,files=files,removed=[])
 fd=os.open(report,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as stream:json.dump(record,stream)
 for entry in files:
  p=Path(entry['path']);info=p.lstat()
  assert stat.S_ISREG(info.st_mode) and (info.st_ino,info.st_size,info.st_mtime_ns)==(entry['inode'],entry['size'],entry['mtime_ns'])
  p.unlink();record['removed'].append(entry['path'])
 record.update(status='complete',free_after=shutil.disk_usage(root).free,removed_allocated=sum(x['allocated'] for x in files))
 with report.open('w') as stream:json.dump(record,stream,indent=2)
 assert record['free_after']>=268435456,'Still insufficient space; no further cleanup authorized'
 print(json.dumps(dict(files_removed=len(record['removed']),allocated_removed=record['removed_allocated'],free_before=record['free_before'],free_after=record['free_after'],reserve_bytes=268435456,locks_held=True,packages_configs_docker_data_untouched=True),indent=2))
