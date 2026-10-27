"""Temporary bounded operator window; no service/timer configuration changes."""
import fcntl,json,os,stat,subprocess,time
from pathlib import Path
root=Path('/opt/veganmedtech/backups');pidfile=root/'work0020-r10-apt-window.pid';stop=root/'work0020-r10-apt-window.stop'
assert not stop.exists() and not pidfile.exists()
for service in ['apt-daily.service','apt-daily-upgrade.service']:
 assert subprocess.run(['systemctl','is-active','--quiet',service]).returncode!=0
locks=[]
try:
 for name in ['/var/lib/dpkg/lock-frontend','/var/lib/dpkg/lock','/var/lib/apt/lists/lock','/var/cache/apt/archives/lock']:
  fd=os.open(name,os.O_RDWR|os.O_NOFOLLOW);info=os.fstat(fd);assert stat.S_ISREG(info.st_mode) and info.st_uid==0
  fcntl.lockf(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(fd)
 fd=os.open(pidfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:f.write(str(os.getpid()))
 print(json.dumps({'apt_dpkg_locks_held':len(locks),'max_seconds':600,'settings_unchanged':True}),flush=True)
 deadline=time.monotonic()+600
 while time.monotonic()<deadline and not stop.exists():time.sleep(.5)
 print(json.dumps({'window_closed':True,'stop_requested':stop.exists()}),flush=True)
finally:
 if pidfile.exists() and pidfile.read_text()==str(os.getpid()):pidfile.unlink()
 if stop.exists():stop.unlink()
 for fd in locks:os.close(fd)
