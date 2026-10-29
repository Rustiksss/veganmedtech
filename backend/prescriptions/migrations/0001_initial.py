import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DemoPrescription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('confirmation_id', models.UUIDField(unique=True)),
                ('drug_id', models.CharField(max_length=40)),
                ('drug_name', models.CharField(max_length=100)),
                ('catalog_version', models.CharField(max_length=60)),
                ('note', models.CharField(blank=True, max_length=1000)),
                ('confirmed_at', models.DateTimeField(auto_now_add=True)),
                ('synthetic', models.BooleanField(default=True)),
                ('doctor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='confirmed_demo_prescriptions', to=settings.AUTH_USER_MODEL)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='demo_prescriptions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-confirmed_at', '-id'],
                'indexes': [models.Index(fields=['patient', '-confirmed_at', '-id'], name='prescription_patient_history')],
                'constraints': [models.CheckConstraint(condition=models.Q(('synthetic', True)), name='prescription_demo_only')],
            },
        ),
    ]
