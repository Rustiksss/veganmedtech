import os,json,secrets,hashlib
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.conf import settings
from django.db import connection
from django.test import Client
from django.db.migrations.recorder import MigrationRecorder
from allauth.account.models import EmailAddress
from accounts.models import User
from care.models import CareRelationship
from audit.events import record
from prescriptions.models import DemoPrescription

checks=[];created=[];link=None
def check(name,value):
    checks.append(dict(name=name,passed=bool(value)))
    if not value:raise AssertionError(name)
def account(label,role):
    u=User.objects.create_user(f'work26-{label}-{secrets.token_hex(5)}@example.test',password=None,display_name=f'Вымышленный {label} WORK-0026',role=role,doctor_approved=role=='doctor')
    created.append(u.pk);EmailAddress.objects.create(user=u,email=u.email,primary=True,verified=True)
    return u
def client(u):
    c=Client(enforce_csrf_checks=True);c.force_login(u,backend='django.contrib.auth.backends.ModelBackend')
    r=c.get('/',secure=True,HTTP_HOST='94.103.3.149');assert r.status_code==200
    c.defaults.update(HTTP_HOST='94.103.3.149',HTTP_ORIGIN='https://94.103.3.149',HTTP_REFERER='https://94.103.3.149/',HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value)
    return c
try:
    check('new migration applied',MigrationRecorder.Migration.objects.filter(app='prescriptions',name='0001_initial').exists())
    p=account('patient','patient');other=account('other','patient');d=account('doctor','doctor')
    link=CareRelationship.objects.create(patient=p,doctor=d)
    dc=client(d);pc=client(p);path=f'/api/patients/{p.pk}/prescriptions'
    response=dc.get('/api/prescriptions/catalog',secure=True);check('catalog 11 names including Aviandr',response.status_code==200 and len(response.json()['results'])==11 and response.json()['results'][0]['name']=='Авиандр')
    response=dc.post(path+'/preview',{'drug_id':'aviandr','note':'Вымышленная запись проверки публикации WORK-0026.'},content_type='application/json',secure=True)
    check('preview does not create record (status '+str(response.status_code)+')',response.status_code==200 and not DemoPrescription.objects.filter(patient=p).exists())
    body={'proposal_token':response.json()['proposal_token'],'confirmed':True}
    first=dc.post(path,body,content_type='application/json',secure=True);second=dc.post(path,body,content_type='application/json',secure=True)
    check('confirmed once and safe retry',first.status_code==201 and second.status_code==200 and first.json()['id']==second.json()['id'] and DemoPrescription.objects.filter(patient=p).count()==1)
    own=pc.get('/api/me/prescriptions',secure=True);check('patient reads own saved Aviandr',own.status_code==200 and own.json()['results'][0]['id']==first.json()['id'])
    check('foreign patient denied',dc.get(f'/api/patients/{other.pk}/prescriptions',secure=True).status_code==404)
    check('patient cannot prescribe',pc.post(path,body,content_type='application/json',secure=True).status_code==403)
finally:
    if link:CareRelationship.objects.filter(pk=link.pk).update(active=False)
    if created:User.objects.filter(pk__in=created).update(is_active=False)
    for uid in created:record(None,'demo.cleanup',uid,subject='service:work0026')

check('own synthetic accounts inactive and relationship revoked',not User.objects.filter(pk__in=created,is_active=True).exists() and not CareRelationship.objects.filter(pk=link.pk,active=True).exists())
with connection.cursor() as c:
    c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name")
    tables=[r[0] for r in c.fetchall()];counts={}
    for table in tables:
        c.execute('SELECT count(*) FROM '+connection.ops.quote_name(table));counts[table]=c.fetchone()[0]
print(json.dumps(dict(checks=checks,counts=counts,created_synthetic_accounts=len(created),model=settings.POLZA_MODEL,alerting_mode=settings.ASSISTANT_ALERTING_MODE),ensure_ascii=False))
