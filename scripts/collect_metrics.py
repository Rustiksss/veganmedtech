#!/usr/bin/env python3
"""One read-only snapshot; standard library locally, existing Django inside the app."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import socket
import ssl
import statistics
import subprocess
import time
import urllib.request


def summary(values):
    values = sorted(float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0)
    return {"samples": len(values), "mean_ms": statistics.mean(values) if values else None,
            "p50_ms": statistics.median(values) if values else None,
            "p95_ms": values[math.ceil(.95 * len(values)) - 1] if values else None,
            "max_ms": max(values) if values else None}


def access_metrics(text):
    # Existing format: %(m)s %(s)s %(D)s; Docker optionally prepends RFC3339.
    pattern = re.compile(r"(?:\d{4}-\d\d-\d\dT[\d:.+\-]+Z? )?(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) ([1-5]\d\d) (\d+)")
    counts = Counter(); durations = []; successful = []; ignored = 0
    for line in text.splitlines():
        match = pattern.fullmatch(line.strip())
        if not match:
            ignored += 1
            continue
        status, elapsed = int(match[2]), int(match[3]) / 1000
        counts[str(status)] += 1; durations.append(elapsed)
        if status < 400: successful.append(elapsed)
    total = sum(counts.values())
    errors = sum(n for code, n in counts.items() if int(code) >= 500)
    return {"requests_observed": total, "status_counts": dict(counts), "latency": summary(durations),
            "successful_latency": summary(successful), "server_error_fraction": errors / total if total else None,
            "access_denials_401_403": counts["401"] + counts["403"], "ignored_lines": ignored,
            "coverage_complete": False, "tail_limit": 5000}


def byte_size(value):
    match = re.fullmatch(r"\s*([\d.]+)\s*(B|kB|KB|MB|GB|KiB|MiB|GiB)\s*", value)
    if not match: return None
    factors = {"B": 1, "kB": 1000, "KB": 1000, "MB": 1000**2, "GB": 1000**3,
               "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}
    return int(float(match[1]) * factors[match[2]])


APP_PROBE = r'''
import os,json,time
from datetime import timedelta
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.conf import settings
from django.db import connection,transaction
from django.db.models import Count,F
from django.utils import timezone
from accounts.models import User
from care.models import CareRelationship
from reports.models import SelfReport
from assistant.models import AssistantTurn,AssistantNotification
from assistant.alerting import POLICY
from audit.models import AuditEvent
since=timezone.now()-timedelta(hours=HOURS)
def groups(qs,field,allowed):
 result={key:0 for key in allowed}
 for row in qs.order_by().values(field).annotate(n=Count('pk')):
  key=row[field] if row[field] in allowed else 'other'
  result[key]=result.get(key,0)+row['n']
 return result
def durations(qs,expression):
 return [v.total_seconds()*1000 for v in qs.order_by('-pk').annotate(elapsed=expression).values_list('elapsed',flat=True)[:5000] if v is not None]
with transaction.atomic():
 with connection.cursor() as c:
  c.execute('SET TRANSACTION READ ONLY');c.execute("SET LOCAL statement_timeout = '5s'")
  started=time.perf_counter();c.execute('SELECT 1');c.fetchone();probe_ms=(time.perf_counter()-started)*1000
  c.execute('SELECT pg_database_size(current_database())');size=c.fetchone()[0]
  c.execute('SELECT numbackends,xact_commit,xact_rollback,blks_read,blks_hit FROM pg_stat_database WHERE datname=current_database()');dbstats=dict(zip(['connections','commits','rollbacks','blocks_read','blocks_hit'],c.fetchone()))
 turns=AssistantTurn.objects.filter(created_at__gte=since)
 events=AssistantNotification.objects.filter(created_at__gte=since,policy_version=POLICY['policy_version'])
 result={'read_only':True,'database_probe_ms':probe_ms,'database_bytes':size,'database_cumulative':dbstats,
  'row_counts':{name:model.objects.count() for name,model in [('users',User),('relationships',CareRelationship),('self_reports',SelfReport),('assistant_turns',AssistantTurn),('notifications',AssistantNotification),('audit',AuditEvent)]},
  'turn_states':groups(turns,'status',['pending','completed','failed','interrupted']),
  'analysis_states':groups(turns,'analysis_status',['not_evaluated','matched','no_match','uncertain','failed']),
  'audit_outcomes':groups(AuditEvent.objects.filter(created_at__gte=since),'outcome',['success','denied']),
  'demo_events':events.count(),'demo_seen':events.filter(seen_at__isnull=False).count(),
  'evaluated_turns':turns.filter(analysis_status__in=['matched','no_match','uncertain']).count(),
  'evaluated_with_policy_version':turns.filter(analysis_status__in=['matched','no_match','uncertain']).exclude(policy_version='').count(),
  'rule_version':POLICY['policy_version'],'rule_categories':len(POLICY['categories']),
  'duration_samples_ms':{
   'completed_turn':durations(turns.filter(status='completed',finished_at__isnull=False),F('finished_at')-F('created_at')),
   'failed_turn':durations(turns.filter(status__in=['failed','interrupted'],finished_at__isnull=False),F('finished_at')-F('created_at')),
   'demo_event_available':durations(events,F('created_at')-F('turn__created_at')),
   'demo_seen':durations(events.filter(seen_at__isnull=False),F('seen_at')-F('created_at'))},
  'configuration':{'django':django.get_version(),'database_vendor':connection.vendor,
   'session_secure':settings.SESSION_COOKIE_SECURE,'session_httponly':settings.SESSION_COOKIE_HTTPONLY,
   'csrf_secure':settings.CSRF_COOKIE_SECURE,'debug':settings.DEBUG,
   'clinical_detection_enabled':POLICY['clinical_detection_enabled'],'alerting_mode':settings.ASSISTANT_ALERTING_MODE}}
print(json.dumps(result))
'''


def command(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=25, **kwargs).stdout


def collect_host(hours):
    result = {"sources": {}}
    def collect(name, callback):
        try:
            result[name] = callback(); result["sources"][name] = "ok"
        except Exception:
            # Never copy subprocess stderr, upstream content or exception text.
            result[name] = None; result["sources"][name] = "unavailable"
    collect("http", lambda: access_metrics(command(["docker", "logs", "--timestamps", "--since", f"{hours}h", "--tail", "5000", "veganmedtech-app-1"])))
    def app():
        value = json.loads(command(["docker", "exec", "-i", "veganmedtech-app-1", "python", "-"], input=f"HOURS={hours}\n"+APP_PROBE))
        value["latencies"] = {k: summary(v) for k,v in value.pop("duration_samples_ms").items()}
        return value
    collect("app", app)
    def resources():
        rows = command(["docker", "stats", "--no-stream", "--format", "{{json .}}", "veganmedtech-app-1", "veganmedtech-db-1", "veganmedtech-mailpit-1"])
        containers = []
        for line in rows.splitlines():
            row = json.loads(line); memory = row["MemUsage"].split("/")
            containers.append({"service": row["Name"].removeprefix("veganmedtech-").removesuffix("-1"),
                "cpu_percent": float(row["CPUPerc"].rstrip("%")), "memory_used_bytes": byte_size(memory[0]),
                "memory_display_limit_bytes": byte_size(memory[1])})
        disk = os.statvfs("/opt")
        memory = {line.split(':')[0]: int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:','MemAvailable:'))}
        return {"containers": containers, "disk_free_bytes": disk.f_bavail*disk.f_frsize,
                "memory": memory, "load_average": list(os.getloadavg()), "capacity_users": None}
    collect("resources", resources)
    def runtime():
        args = json.loads(command(["docker", "inspect", "--format", "{{json .Config.Cmd}}", "veganmedtech-app-1"]))
        workers = next((int(a.split('=',1)[1]) for a in args if a.startswith('--workers=')),None)
        return {"workers": workers, "app_containers": 1,
            "app_started_at": command(["docker","inspect","--format","{{.State.StartedAt}}","veganmedtech-app-1"]).strip(),
            "health": {name: command(["docker","inspect","--format","{{.State.Health.Status}}",f"veganmedtech-{name}-1"]).strip() for name in ['app','db','mailpit']}}
    collect("runtime", runtime)
    def backups():
        files = [p for p in Path('/opt/veganmedtech/backups').glob('*.dump') if p.is_file() and not p.is_symlink()]
        latest = max(files,key=lambda p:p.stat().st_mtime) if files else None
        return {"dump_count": len(files), "latest_bytes": latest.stat().st_size if latest else None,
                "latest_age_seconds": max(0,time.time()-latest.stat().st_mtime) if latest else None,
                "restore_seconds": None, "actual_data_loss": None, "guaranteed_rpo_seconds": None}
    collect("backups", backups)
    def public():
        started = time.perf_counter()
        with urllib.request.urlopen('https://94.103.3.149/health/ready',timeout=10) as r:
            ready = json.load(r).get('ready') is True
        elapsed = (time.perf_counter()-started)*1000
        with urllib.request.urlopen('https://94.103.3.149/',timeout=10) as r:
            headers = {k:r.headers.get(k) for k in ['Strict-Transport-Security','X-Content-Type-Options','X-Frame-Options','Referrer-Policy']}
        with socket.create_connection(('94.103.3.149',443),timeout=10) as s:
            with ssl.create_default_context().wrap_socket(s,server_hostname='94.103.3.149') as tls:
                expiry = ssl.cert_time_to_seconds(tls.getpeercert()['notAfter'])
        return {"ready": ready, "probe_ms": elapsed, "vantage":"deployment_host", "tls_verified":True,
                "certificate_expires_in_seconds":expiry-time.time(), "headers":headers}
    collect("public", public)
    return result


def validate_scenario(value):
    allowed = {'login','self_report','view_history','assistant_message','doctor_notification'}
    if not isinstance(value,dict) or value.get('scenario') not in allowed: raise ValueError('Unknown scenario')
    result = {'scenario':value['scenario']}
    for key in ['duration_ms','activation_count','field_change_count','viewport_width','viewport_height']:
        v = value.get(key)
        if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v < 0: raise ValueError('Invalid scenario measurement')
        result[key] = v
    result['browser'] = value.get('browser') if value.get('browser') in ['Firefox','Chrome','Edge','Safari'] else 'other'
    return result  # Extra fields, URLs, values and identifiers are never exported.


def make_report(data, hours, scenario=None):
    app = data.get('app') or {}; latency = app.get('latencies',{}); config = app.get('configuration',{})
    sections = [
        ('Быстродействие','partial',{'http':data.get('http'),'app':latency,'public':data.get('public')},'Демособытие доступно в БД; доставка в браузер и рекомендации не измерены.'),
        ('Качество извлечения','not_implemented',{'precision':None,'recall':None},'Извлечение истории болезни не реализовано; качество демоанализа не равно этой метрике.'),
        ('Надёжность и входные данные','measured' if app else 'unavailable',{'turn_states':app.get('turn_states'),'analysis_states':app.get('analysis_states'),'audit_outcomes':app.get('audit_outcomes')},'Ошибки отражают наблюдаемое окно, не универсальную корректность.'),
        ('Эргономика','measured' if scenario else 'not_measured',scenario,'Ручной start/stop; активации и изменения полей считаются отдельно, не все физические действия.'),
        ('Обоснованность выводов','partial',{'evaluated_turns':app.get('evaluated_turns'),'with_policy_version':app.get('evaluated_with_policy_version')},'Наличие версии не подтверждает клиническую обоснованность; медицинских рекомендаций нет.'),
        ('Устойчивость к нагрузке','partial',data.get('resources'),'Снимок ресурсов текущей нагрузки, не нагрузочный тест и не предел пользователей.'),
        ('Восстановление и сохранность','partial',data.get('backups'),'Возраст копии не является гарантией RPO; новый restore и сбой не проводились.'),
        ('Кроссплатформенность','partial',{'runtime':config.get('django'),'database_vendor':config.get('database_vendor'),'browser_sample':scenario},'Один браузерный образец не доказывает совместимость всех платформ.'),
        ('Масштабируемость','documented',data.get('runtime'),'Один узел приложения/БД; число workers не равно числу поддерживаемых пользователей.'),
        ('Расширяемость правил','documented',{'demo_policy_version':app.get('rule_version'),'demo_categories':app.get('rule_categories'),'questionnaires':4,'clinical_drug_registry':False},'Четыре учебные шкалы в questionnaires.js; правила отдельно, изменение кода требует поставки/проверки.'),
        ('Гибкость данных','measured' if app else 'unavailable',{'database_bytes':app.get('database_bytes'),'probe_ms':app.get('database_probe_ms'),'cumulative':app.get('database_cumulative'),'rows':app.get('row_counts')},'SELECT1 — контроль чтения, не скорость всех запросов; статистика PostgreSQL накопительная.'),
        ('Полнота модели','documented',{'rows':app.get('row_counts'),'clinical_engine':False,'prescriptions':False},'Есть аккаунты/связи/самоотчёты/чат/демособытия/аудит; полного клинического контура нет.'),
        ('Защищённость данных','partial',{'configuration':config,'public':data.get('public'),'audit_outcomes':app.get('audit_outcomes')},'Проверка механизмов/отказов, не аудит безопасности или подтверждение правового соответствия.')]
    return {'schema_version':1,'collected_at':datetime.now(timezone.utc).isoformat(),'window_hours':hours,
            'sources':data.get('sources',{}),'limitations':['Только агрегаты; в БД есть синтетические тестовые записи.',
            'Логи только текущего контейнера, до5000 строк; полнота окна не гарантирована.',
            'Длительности из БД — до5000 последних значений каждого вида; пустая выборка даёт null.'],
            'metrics':[{'requirement':f'NFR-{i:03}','name':name,'status':status,'data':values,'limitation':note}
                       for i,(name,status,values,note) in enumerate(sections,1)]}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ssh',default='veganmedtech-server')
    p.add_argument('--hours',type=int,default=24);p.add_argument('--output',type=Path)
    p.add_argument('--scenario-file',type=Path);p.add_argument('--host',action='store_true',help=argparse.SUPPRESS);args=p.parse_args()
    if not 1<=args.hours<=168: p.error('--hours must be 1..168')
    if args.host:
        print(json.dumps(collect_host(args.hours),allow_nan=False));return
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*',args.ssh):p.error('Use a saved SSH alias')
    command_line=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ForwardAgent=no','-o','ClearAllForwardings=yes','-o','ConnectTimeout=10',args.ssh,f'python3 - --host --hours {args.hours}']
    try:
        raw=subprocess.run(command_line,input=Path(__file__).read_text(),text=True,capture_output=True,timeout=100,check=True)
        data=json.loads(raw.stdout)
        scenario=validate_scenario(json.loads(args.scenario_file.read_text())) if args.scenario_file else None
        report=make_report(data,args.hours,scenario)
    except (subprocess.SubprocessError,ValueError,OSError):raise SystemExit('Collection failed; no report fabricated. Check SSH/source availability.') from None
    text=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text)
        print(json.dumps({'output':str(args.output),'sections':len(report['metrics']),'sources':report['sources']}))
    else:print(text,end='')
    if any(v!='ok' for v in report['sources'].values()):raise SystemExit(1)


if __name__=='__main__':main()
