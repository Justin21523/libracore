from __future__ import annotations

import csv
import io

from django.contrib.contenttypes.models import ContentType
from django.forms.models import model_to_dict

from .models import AuditLog


def write_audit_log(
    *,
    action: str,
    entity,
    before: dict | None = None,
    after: dict | None = None,
    actor=None,
    ip_address: str | None = None,
    user_agent: str = "",
) -> AuditLog:
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        entity_type=ContentType.objects.get_for_model(entity.__class__),
        entity_id=str(entity.id),
        before=before or {},
        after=after or {},
        ip_address=ip_address,
        user_agent=user_agent,
    )


def actor_kwargs(actor_context) -> dict:
    return {
        "actor": actor_context.actor if getattr(actor_context, "actor", None) else None,
        "ip_address": getattr(actor_context, "ip_address", None),
        "user_agent": getattr(actor_context, "user_agent", ""),
    }


def model_snapshot(instance) -> dict:
    values = model_to_dict(instance)
    return {key: _stringify(value) for key, value in values.items()}


def json_diff(before: dict, after: dict) -> list[dict]:
    changes = []
    keys = sorted(set((before or {}).keys()) | set((after or {}).keys()))
    for key in keys:
        old = (before or {}).get(key)
        new = (after or {}).get(key)
        if isinstance(old, dict) and isinstance(new, dict):
            for child in json_diff(old, new):
                changes.append({**child, "path": f"{key}.{child['path']}"})
        elif old != new:
            changes.append({"path": key, "before": old, "after": new})
    return changes


def filtered_audit_logs(params):
    logs = AuditLog.objects.select_related("actor", "entity_type").all()
    if params.get("actor"):
        logs = logs.filter(actor__username__icontains=params["actor"])
    if params.get("action"):
        logs = logs.filter(action__icontains=params["action"])
    if params.get("entity_type"):
        logs = logs.filter(entity_type__model=params["entity_type"])
    if params.get("date_from"):
        logs = logs.filter(created_at__date__gte=params["date_from"])
    if params.get("date_to"):
        logs = logs.filter(created_at__date__lte=params["date_to"])
    return logs


def audit_logs_csv(queryset) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["created_at", "actor", "action", "entity_type", "entity_id"])
    for log in queryset:
        writer.writerow(
            [
                log.created_at.isoformat(),
                log.actor.username if log.actor else "",
                log.action,
                log.entity_type.model,
                log.entity_id,
            ]
        )
    return output.getvalue()


def _stringify(value):
    if isinstance(value, list):
        return [str(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value) if value is not None else None
