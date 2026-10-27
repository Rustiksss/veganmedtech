from audit.models import AuditEvent

def record(actor, action, object_id="", outcome="success", subject=""):
    return AuditEvent.objects.create(actor=actor if actor and actor.is_authenticated else None,
        subject=subject, action=action, object_id=str(object_id), outcome=outcome)
