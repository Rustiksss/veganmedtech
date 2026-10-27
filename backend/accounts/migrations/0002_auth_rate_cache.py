from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunSQL(
        'CREATE TABLE auth_rate_limits (cache_key varchar(255) PRIMARY KEY, value text NOT NULL, expires timestamp with time zone NOT NULL); CREATE INDEX auth_rate_expires ON auth_rate_limits (expires);',
        'DROP TABLE auth_rate_limits;',
    )]
