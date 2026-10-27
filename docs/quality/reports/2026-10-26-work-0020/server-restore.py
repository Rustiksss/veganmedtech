"""Restore stays on the deployment host; only checks/counts leave it."""
import hashlib,json,os,subprocess,time,urllib.request
from pathlib import Path

ROOT=Path('/opt/veganmedtech')
NAME='veganmedtech-work0020-restore'
IMAGE='postgres:18.6-bookworm@sha256:afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c'
BACKUP=ROOT/'backups/work0020-verified-final.dump'
baseline=json.loads((ROOT/'backups/work0020-preservation.json').read_text())

def command(args,**kwargs):
    return subprocess.run(args,check=True,capture_output=True,**kwargs)

def sql(container,statement,database=None):
    # User/database names are expanded only inside the existing DB container.
    args=['docker','exec','-i',container]
    if database:
        args+=['psql','-X','-qAt','-v','ON_ERROR_STOP=1','-U','compass','-d',database]
    else:
        args+=['sh','-c','exec psql -X -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"']
    return command(args,input=statement.encode()).stdout.decode().strip()

def quote(value):
    return '"'+value.replace('"','""')+'"'

def fingerprint(container,database=None):
    names=sql(container,"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename",database).splitlines()
    result={}
    for name in names:
        query="SELECT json_build_array(count(*),md5(COALESCE(string_agg(row_to_json(t)::text,E'\\n' ORDER BY row_to_json(t)::text),''))) FROM "+quote(name)+' t'
        result[name]=json.loads(sql(container,query,database))
    return result

def free():
    st=os.statvfs('/opt');return st.f_bavail*st.f_frsize

memory=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
assert memory>=384*1024*1024,'Not enough memory for bounded isolated restore'
assert free()>=268435456
assert not BACKUP.exists(),'Do not overwrite an existing backup'
assert subprocess.run(['docker','container','inspect',NAME],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0
before=fingerprint('veganmedtech-db-1')
fd=os.open(BACKUP,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'wb') as output:
    subprocess.run(['docker','exec','veganmedtech-db-1','sh','-c','exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner'],stdout=output,check=True)
assert before==fingerprint('veganmedtech-db-1'),'Source changed during dump; do not claim an exact comparison'
with BACKUP.open('rb') as source:
    subprocess.run(['docker','exec','-i','veganmedtech-db-1','pg_restore','--list'],stdin=source,stdout=subprocess.DEVNULL,check=True)
started=False
result={'location':'same server; network none; tmpfs PGDATA','memory_available_before_bytes':memory,'disk_before_bytes':free()}
try:
    command(['docker','run','-d','--name',NAME,'--network','none','--memory','256m','--memory-swap','256m',
             '--mount','type=tmpfs,destination=/var/lib/postgresql,tmpfs-size=134217728',
             '-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_USER=compass','-e','POSTGRES_DB=compass_restore_work0020',
             IMAGE,'postgres','-c','shared_buffers=16MB','-c','max_connections=10'])
    started=True
    inspection=json.loads(command(['docker','inspect',NAME]).stdout)[0]
    assert inspection['HostConfig']['NetworkMode']=='none'
    assert inspection['HostConfig']['Memory']==inspection['HostConfig']['MemorySwap']==268435456
    assert len(inspection['Mounts'])==1 and inspection['Mounts'][0]['Type']=='tmpfs'
    for attempt in range(60):
        if subprocess.run(['docker','exec',NAME,'pg_isready','-U','compass','-d','compass_restore_work0020'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:break
        time.sleep(.5)
    else:raise AssertionError('Temporary PostgreSQL did not become ready')
    with BACKUP.open('rb') as source:
        subprocess.run(['docker','exec','-i',NAME,'pg_restore','--exit-on-error','--no-owner','-U','compass','-d','compass_restore_work0020'],stdin=source,check=True,stdout=subprocess.DEVNULL)
    restored=fingerprint(NAME,'compass_restore_work0020')
    assert restored==before,'Full table contents differ'
    original_preserved=True
    for table,info in baseline['tables'].items():
        fields=','.join(quote(c) for c in info['columns'])
        query='SELECT id,md5(row_to_json(t)::text) FROM (SELECT '+fields+' FROM '+quote(table)+') t ORDER BY id'
        rows=dict(row.split('|',1) for row in sql(NAME,query,'compass_restore_work0020').splitlines())
        original_preserved &= all(rows.get(pk)==digest for pk,digest in info['rows'].items())
    assert original_preserved
    result.update({'all_public_tables_exactly_match':True,'original_predeploy_rows_preserved':True,
                   'table_counts':{k:v[0] for k,v in restored.items()},'dump_bytes':BACKUP.stat().st_size,
                   'dump_sha256':hashlib.sha256(BACKUP.read_bytes()).hexdigest(),
                   'bounded_ram_no_swap':True,'network_none':True,'no_persistent_volumes':True})
finally:
    if started:command(['docker','rm','-f',NAME])
    result['temporary_container_removed']=subprocess.run(['docker','container','inspect',NAME],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0
    result['disk_after_bytes']=free()
    with urllib.request.urlopen('https://94.103.3.149/health/ready',timeout=10) as response:result['public_app_ready']=json.load(response).get('ready') is True
    print(json.dumps(result),flush=True)
assert result['temporary_container_removed'] and result['public_app_ready'] and result['disk_after_bytes']>=268435456
