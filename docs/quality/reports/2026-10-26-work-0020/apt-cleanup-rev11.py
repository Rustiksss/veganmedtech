"""Approved WORK-0020 r11: one exact, locked cleanup; no secrets leave the host."""
import hashlib,json,subprocess
from pathlib import Path
OUT=Path(__file__).resolve().parent
manifest=json.loads((OUT/'apt-inventory-rev10.json').read_text())['apt_files']
assert len(manifest)==50
assert hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()=='c51285891a25aea11ca6d0ecf8c46f3d595c4d5e4494aeb8462086f8214614e9'
SOURCE=r'''import contextlib,fcntl,hashlib,json,os,signal,stat,subprocess,time,urllib.request
from pathlib import Path
ROOT=Path('/opt/veganmedtech');REPORT=ROOT/'backups/work0020-r11-apt-cleanup.json';BASELINE=ROOT/'backups/work0020-r11-before-apt.json'
assert not REPORT.exists() and not BASELINE.exists()
expected={'current':'releases/20261026T172503Z-368b0976','previous':'releases/20261026T171831Z-b0771a9e'}
def deadline(signum,frame):raise TimeoutError('Bounded cleanup window expired')
signal.signal(signal.SIGALRM,deadline);signal.alarm(600)
def links():return {k:os.readlink(ROOT/k) for k in expected}
def health():return {n:subprocess.check_output(['docker','inspect','--format','{{.State.Health.Status}}',n],text=True).strip() for n in ['veganmedtech-app-1','veganmedtech-db-1','veganmedtech-mailpit-1']}
def free():s=os.statvfs('/opt');return s.f_bavail*s.f_frsize
def digest(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def cache_files():
 return {str(p):[p.lstat().st_ino,p.lstat().st_size,p.lstat().st_mtime_ns] for base in ['/var/cache/apt','/var/lib/apt/lists'] for p in Path(base).rglob('*') if p.name!='lock' and stat.S_ISREG(p.lstat().st_mode)}
def state():
 paths=[Path('/var/lib/dpkg/status'),ROOT/'config/server.env',ROOT/'config/mailpit-access.json',Path('/etc/veganmedtech/Caddyfile'),Path('/etc/veganmedtech/proxy.env')]
 for folder in ['/etc/apt','/etc/systemd/system']:
  paths += [p for p in Path(folder).rglob('*') if p.is_file() and not p.is_symlink()]
 paths += [Path('/usr/lib/systemd/system')/n for n in ['apt-daily.service','apt-daily.timer','apt-daily-upgrade.service','apt-daily-upgrade.timer']]
 paths += [p for p in Path('/var/lib/veganmedtech-caddy/production').rglob('*') if p.is_file() and p.suffix in ['.crt','.key']]
 with urllib.request.urlopen('http://127.0.0.1:18025/api/v1/messages?limit=1000',timeout=10) as r:mail=json.load(r)
 assert mail.get('total',len(mail['messages']))<=1000
 return {'hashes':{str(p):digest(p) for p in paths},'mail_ids':sorted(m['ID'] for m in mail['messages']),'mailpit_id':subprocess.check_output(['docker','inspect','--format','{{.Id}}','veganmedtech-mailpit-1'],text=True).strip(),'timers':{n:subprocess.check_output(['systemctl','is-enabled',n],text=True).strip() for n in ['apt-daily.timer','apt-daily-upgrade.timer']},'links':links()}
def private_json(path,value):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
with contextlib.ExitStack() as stack:
 fd=os.open(ROOT/'.deploy.lock',os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC);f=stack.enter_context(os.fdopen(fd,'r+'));fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
 locks=['/var/lib/dpkg/lock-frontend','/var/lib/dpkg/lock','/var/lib/apt/lists/lock','/var/cache/apt/archives/lock']
 for n in locks:
  fd=os.open(n,os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC);i=os.fstat(fd);assert stat.S_ISREG(i.st_mode) and i.st_uid==0
  f=stack.enter_context(os.fdopen(fd,'r+'));fcntl.lockf(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
 for n in ['apt-daily.service','apt-daily-upgrade.service']:
  assert subprocess.check_output(['systemctl','show',n,'--property=ActiveState','--value'],text=True).strip()=='inactive'
 assert links()==expected and all(v=='healthy' for v in health().values())
 before_cache=cache_files();wanted={e['path'] for e in MANIFEST};assert len(wanted)==50
 assert {p for p,v in before_cache.items() if v[1]>0}==wanted
 versions={}
 for e in MANIFEST:
  p=Path(e['path']);assert p in [Path('/var/cache/apt/pkgcache.bin'),Path('/var/cache/apt/srcpkgcache.bin')] or p.parent==Path('/var/lib/apt/lists')
  assert p.name!='lock' and all(not parent.is_symlink() for parent in [p,*p.parents])
  i=p.lstat();assert stat.S_ISREG(i.st_mode) and i.st_uid==e['uid']==0 and i.st_nlink==1
  assert (i.st_size,i.st_blocks*512,int(i.st_mtime))==(e['bytes'],e['allocated_bytes'],e['mtime']),str(p)
  versions[str(p)]=(i.st_ino,i.st_size,i.st_mtime_ns)
 before=state();assert all(v=='enabled' for v in before['timers'].values());private_json(BASELINE,before);available_before=free()
 removed=[]
 try:
  for e in MANIFEST:
   p=Path(e['path']);i=p.lstat();assert (i.st_ino,i.st_size,i.st_mtime_ns)==versions[str(p)]
   p.unlink();removed.append(str(p))
  after_cache=cache_files();assert after_cache=={p:v for p,v in before_cache.items() if p not in wanted}
  after=state();same=after==before;available_after=free();h=health()
  with urllib.request.urlopen('https://94.103.3.149/health/ready',timeout=10) as r:ready=json.load(r)['ready'] is True
  result={'task':'WORK-0020','approved_revision':11,'removed_files':removed,'removed_count':len(removed),'allocated_removed':sum(e['allocated_bytes'] for e in MANIFEST),'available_before':available_before,'available_after':available_after,'freed_bytes':available_after-available_before,'other_cache_files_unchanged':True,'installed_packages_config_tls_mail_links_preserved':same,'mail_count':len(before['mail_ids']),'timers':after['timers'],'health':h,'public_ready':ready,'only_exact_approved_paths':set(removed)==wanted,'locks_held':locks,'window_max_seconds':600}
  private_json(REPORT,result);print(json.dumps(result),flush=True)
  assert same and ready and all(v=='healthy' for v in h.values()) and available_after>=268435456
 except BaseException:
  if not REPORT.exists():private_json(REPORT,{'task':'WORK-0020','approved_revision':11,'partial_removed':removed,'failed':True,'no_further_cleanup_authorized':True})
  raise
signal.alarm(0)
'''
code='MANIFEST='+repr(manifest)+'\n'+SOURCE
compile(code,'approved-apt-cleanup','exec')
ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no','-o','ClearAllForwardings=yes','-o','ConnectTimeout=10','veganmedtech-server','python3 -']
r=subprocess.run(ssh,input=code,text=True,capture_output=True)
(OUT/'apt-cleanup-rev11.txt').write_text(r.stdout+r.stderr)
if r.returncode:raise SystemExit('Cleanup stopped; inspect apt-cleanup-rev11.txt; do not retry or expand paths')
d=json.loads(r.stdout);(OUT/'apt-cleanup-rev11.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:d[k] for k in ['removed_count','freed_bytes','available_after','installed_packages_config_tls_mail_links_preserved','health','public_ready']}))
