from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("assistant", "0001_initial")]
    operations = [
        migrations.AddField(model_name="assistantturn", name="alerting_mode", field=models.CharField(
            choices=[("off", "Выключен"), ("demo", "Демонстрация")], default="off", max_length=8)),
        migrations.AddField(model_name="assistantturn", name="analysis_status", field=models.CharField(
            choices=[("not_evaluated", "Не выполнялся"), ("matched", "Возможный сигнал"), ("no_match", "Совпадений нет"),
                     ("uncertain", "Неоднозначно"), ("failed", "Проверка не выполнена")], default="not_evaluated", max_length=16)),
        migrations.AddField(model_name="assistantturn", name="policy_version", field=models.CharField(blank=True, max_length=50)),
        migrations.AddField(model_name="assistantturn", name="analysis", field=models.JSONField(default=list)),
        migrations.AddConstraint(model_name="assistantturn", constraint=models.CheckConstraint(
            condition=models.Q(alerting_mode__in=["off", "demo"]), name="assistant_valid_alert_mode")),
        migrations.AddConstraint(model_name="assistantturn", constraint=models.CheckConstraint(
            condition=models.Q(analysis_status__in=["not_evaluated", "matched", "no_match", "uncertain", "failed"]),
            name="assistant_valid_analysis")),
    ]
