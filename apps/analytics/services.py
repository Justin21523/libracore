from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.core.files.base import ContentFile
from django.db.models import Count, QuerySet, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.acquisitions.models import AcquisitionOrder, AcquisitionOrderLine, Invoice
from apps.circulation.models import Loan
from apps.core.roles import (
    ROLE_ACQUISITIONS,
    ROLE_CATALOGER,
    ROLE_CIRCULATION,
    ROLE_ERM,
    ROLE_REPOSITORY,
    user_has_role,
)
from apps.erm.models import ElectronicResource, License, Package
from apps.holdings.models import Item
from apps.marc.models import MarcImportBatch, MarcImportRecord
from apps.repository.models import DigitalObject, FileAsset
from apps.serials.models import Issue

from .models import ReportDefinition, ReportRun


class ReportPermissionError(PermissionError):
    pass


class UnknownReportError(ValueError):
    pass


@dataclass(frozen=True)
class ReportSpec:
    code: str
    name: str
    description: str
    required_role: str
    runner: Callable[[dict[str, Any]], dict[str, Any]]
    default_parameters: dict[str, Any] | None = None


def builtin_report_specs() -> dict[str, ReportSpec]:
    specs = [
        ReportSpec(
            code="holdings.inventory_summary",
            name="館藏單冊狀態彙總",
            description="依分館、館藏地、單冊狀態與資源類型彙總 item 數量。",
            required_role="",
            runner=_holdings_inventory_summary,
        ),
        ReportSpec(
            code="circulation.overdue_loans",
            name="逾期借閱清單",
            description="列出目前逾期且未歸還的借閱紀錄。",
            required_role=ROLE_CIRCULATION,
            runner=_circulation_overdue_loans,
        ),
        ReportSpec(
            code="circulation.checkout_trend",
            name="流通借還趨勢",
            description="依日期彙總指定區間內的借出與歸還數。",
            required_role=ROLE_CIRCULATION,
            runner=_circulation_checkout_trend,
            default_parameters={"days": 30},
        ),
        ReportSpec(
            code="circulation.top_titles",
            name="熱門借閱題名",
            description="依題名彙總指定區間內借閱次數。",
            required_role=ROLE_CIRCULATION,
            runner=_circulation_top_titles,
            default_parameters={"days": 30, "limit": 100},
        ),
        ReportSpec(
            code="acquisitions.order_summary",
            name="採購訂單與發票彙總",
            description="依訂單狀態彙總訂單、訂單明細、驗收與發票對帳狀態。",
            required_role=ROLE_ACQUISITIONS,
            runner=_acquisitions_order_summary,
        ),
        ReportSpec(
            code="serials.issue_exceptions",
            name="期刊缺期與延遲清單",
            description="列出缺期、已催缺與過期未到的期刊 issue。",
            required_role=ROLE_ACQUISITIONS,
            runner=_serials_issue_exceptions,
        ),
        ReportSpec(
            code="erm.expiring_resources",
            name="即將到期電子資源",
            description="列出指定天數內到期的授權與套裝。",
            required_role=ROLE_ERM,
            runner=_erm_expiring_resources,
            default_parameters={"days": 30},
        ),
        ReportSpec(
            code="cataloging.marc_import_errors",
            name="MARC 匯入錯誤與衝突",
            description="列出 MARC 匯入批次與紀錄的錯誤、衝突、驗證訊息。",
            required_role=ROLE_CATALOGER,
            runner=_cataloging_marc_import_errors,
            default_parameters={"limit": 100},
        ),
        ReportSpec(
            code="repository.digital_object_summary",
            name="數位典藏物件與檔案彙總",
            description="依典藏物件狀態、檔案 MIME type 與存取層級彙總。",
            required_role=ROLE_REPOSITORY,
            runner=_repository_digital_object_summary,
        ),
    ]
    return {spec.code: spec for spec in specs}


def seed_builtin_report_definitions() -> list[ReportDefinition]:
    definitions = []
    for spec in builtin_report_specs().values():
        definition, _ = ReportDefinition.objects.update_or_create(
            code=spec.code,
            defaults={
                "name": spec.name,
                "description": spec.description,
                "query_spec": {
                    "builtin": True,
                    "parameters": spec.default_parameters or {},
                },
                "required_permission": spec.required_role,
            },
        )
        definitions.append(definition)
    return definitions


def can_run_report(user, code: str) -> bool:
    spec = builtin_report_specs().get(code)
    if not spec:
        return False
    if spec.required_role:
        return user_has_role(user, spec.required_role)
    return user_has_role(user)


def visible_report_definitions(user) -> QuerySet[ReportDefinition]:
    seed_builtin_report_definitions()
    codes = [code for code in builtin_report_specs() if can_run_report(user, code)]
    return ReportDefinition.objects.filter(code__in=codes).order_by("name")


def visible_report_codes(user) -> set[str]:
    return {definition.code for definition in visible_report_definitions(user)}


def run_report(code: str, parameters: dict[str, Any] | None = None, actor=None) -> ReportRun:
    specs = builtin_report_specs()
    spec = specs.get(code)
    if not spec:
        raise UnknownReportError(f"Unknown report: {code}")
    if actor is not None and not can_run_report(actor, code):
        raise ReportPermissionError(f"Permission denied for report: {code}")

    definition = ReportDefinition.objects.filter(code=code).first()
    normalized_parameters = _normalize_parameters(
        {**(spec.default_parameters or {}), **(parameters or {})}
    )
    run = ReportRun.objects.create(
        report_definition=definition,
        code=code,
        name=spec.name,
        status=ReportRun.Status.RUNNING,
        requested_by=actor if getattr(actor, "is_authenticated", False) else None,
        parameters=normalized_parameters,
        started_at=timezone.now(),
    )
    try:
        result = spec.runner(normalized_parameters)
        result.setdefault("generated_at", timezone.now().isoformat())
        result = _json_ready(result)
        csv_content = _result_to_csv(result)
        run.csv_file.save(
            f"{code.replace('.', '-')}-{timezone.now():%Y%m%d%H%M%S}.csv",
            ContentFile(csv_content.encode("utf-8-sig")),
            save=False,
        )
        run.result_json = result
        run.record_count = len(result.get("rows", []))
        run.status = ReportRun.Status.COMPLETED
    except Exception as exc:  # noqa: BLE001
        run.status = ReportRun.Status.FAILED
        run.error_report = str(exc)
    run.completed_at = timezone.now()
    run.save()
    return run


def _normalize_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(parameters)
    if "limit" in normalized:
        try:
            normalized["limit"] = min(max(int(normalized["limit"]), 1), 500)
        except (TypeError, ValueError):
            normalized["limit"] = 100
    if "days" in normalized:
        try:
            normalized["days"] = min(max(int(normalized["days"]), 1), 730)
        except (TypeError, ValueError):
            normalized["days"] = 30
    return normalized


def _date_range(parameters: dict[str, Any], default_days: int = 30):
    today = timezone.localdate()
    date_to = parse_date(str(parameters.get("date_to") or "")) or today
    date_from = parse_date(str(parameters.get("date_from") or "")) or (
        date_to - timezone.timedelta(days=int(parameters.get("days") or default_days) - 1)
    )
    start = timezone.make_aware(timezone.datetime.combine(date_from, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(date_to, timezone.datetime.max.time()))
    return date_from, date_to, start, end


def _columns(*names: str) -> list[dict[str, str]]:
    return [{"key": name, "label": name.replace("_", " ")} for name in names]


def _empty(value: Any, default: str = "") -> str:
    return default if value in (None, "") else str(value)


def _json_ready(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_ready(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


def _result_to_csv(result: dict[str, Any]) -> str:
    columns = [column["key"] for column in result.get("columns", [])]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in result.get("rows", []):
        writer.writerow({key: row.get(key, "") for key in columns})
    return output.getvalue()


def _holdings_inventory_summary(parameters: dict[str, Any]) -> dict[str, Any]:
    rows = list(
        Item.objects.select_related("holding__branch", "holding__location", "holding__instance")
        .values(
            "holding__branch__code",
            "holding__branch__name",
            "holding__location__code",
            "holding__location__name",
            "holding__instance__resource_type",
            "status",
        )
        .annotate(count=Count("id"))
        .order_by("holding__branch__code", "holding__location__code", "status")
    )
    mapped = [
        {
            "branch_code": row["holding__branch__code"],
            "branch": row["holding__branch__name"],
            "location_code": row["holding__location__code"],
            "location": row["holding__location__name"],
            "resource_type": row["holding__instance__resource_type"],
            "item_status": row["status"],
            "item_count": row["count"],
        }
        for row in rows
    ]
    return {
        "columns": _columns(
            "branch_code",
            "branch",
            "location_code",
            "location",
            "resource_type",
            "item_status",
            "item_count",
        ),
        "rows": mapped,
        "summary": {"total_items": sum(row["item_count"] for row in mapped)},
    }


def _circulation_overdue_loans(parameters: dict[str, Any]) -> dict[str, Any]:
    limit = int(parameters.get("limit") or 100)
    loans = (
        Loan.objects.filter(status=Loan.Status.OPEN, due_at__lt=timezone.now())
        .select_related("patron__user", "item__holding__instance")
        .order_by("due_at")[:limit]
    )
    rows = [
        {
            "loan_id": str(loan.id),
            "patron_barcode": loan.patron.barcode,
            "patron": loan.patron.user.get_username(),
            "item_barcode": loan.item.barcode,
            "title": loan.item.holding.instance.title_statement,
            "due_at": loan.due_at,
            "days_overdue": (timezone.now().date() - timezone.localtime(loan.due_at).date()).days,
        }
        for loan in loans
    ]
    return {
        "columns": _columns(
            "loan_id",
            "patron_barcode",
            "patron",
            "item_barcode",
            "title",
            "due_at",
            "days_overdue",
        ),
        "rows": rows,
        "summary": {"overdue_count": len(rows)},
    }


def _circulation_checkout_trend(parameters: dict[str, Any]) -> dict[str, Any]:
    date_from, date_to, start, end = _date_range(parameters)
    checkout_counts = Counter(
        timezone.localtime(value).date()
        for value in Loan.objects.filter(checked_out_at__gte=start, checked_out_at__lte=end)
        .values_list("checked_out_at", flat=True)
    )
    return_counts = Counter(
        timezone.localtime(value).date()
        for value in Loan.objects.filter(returned_at__gte=start, returned_at__lte=end)
        .values_list("returned_at", flat=True)
    )
    rows = []
    current = date_from
    while current <= date_to:
        rows.append(
            {
                "date": current,
                "checkouts": checkout_counts[current],
                "returns": return_counts[current],
            }
        )
        current += timezone.timedelta(days=1)
    return {
        "columns": _columns("date", "checkouts", "returns"),
        "rows": rows,
        "summary": {
            "date_from": date_from,
            "date_to": date_to,
            "total_checkouts": sum(row["checkouts"] for row in rows),
            "total_returns": sum(row["returns"] for row in rows),
        },
    }


def _circulation_top_titles(parameters: dict[str, Any]) -> dict[str, Any]:
    _, _, start, end = _date_range(parameters)
    limit = int(parameters.get("limit") or 100)
    rows = list(
        Loan.objects.filter(checked_out_at__gte=start, checked_out_at__lte=end)
        .values("item__holding__instance__title_statement")
        .annotate(checkout_count=Count("id"))
        .order_by("-checkout_count", "item__holding__instance__title_statement")[:limit]
    )
    mapped = [
        {
            "title": row["item__holding__instance__title_statement"] or "(無題名)",
            "checkout_count": row["checkout_count"],
        }
        for row in rows
    ]
    return {
        "columns": _columns("title", "checkout_count"),
        "rows": mapped,
        "summary": {"title_count": len(mapped)},
    }


def _acquisitions_order_summary(parameters: dict[str, Any]) -> dict[str, Any]:
    order_rows = list(
        AcquisitionOrder.objects.values("status")
        .annotate(order_count=Count("id"))
        .order_by("status")
    )
    line_rows = list(
        AcquisitionOrderLine.objects.values("receiving_status")
        .annotate(
            line_count=Count("id"),
            ordered_quantity=Sum("quantity"),
            received_quantity=Sum("received_quantity"),
            cancelled_quantity=Sum("cancelled_quantity"),
        )
        .order_by("receiving_status")
    )
    invoice_rows = list(
        Invoice.objects.values("match_status")
        .annotate(invoice_count=Count("id"), total_amount=Sum("total_amount"))
        .order_by("match_status")
    )
    rows = [
        {
            "section": "order",
            "status": row["status"],
            "count": row["order_count"],
            "ordered_quantity": "",
            "received_quantity": "",
            "cancelled_quantity": "",
            "amount": "",
        }
        for row in order_rows
    ]
    rows.extend(
        {
            "section": "order_line",
            "status": row["receiving_status"],
            "count": row["line_count"],
            "ordered_quantity": row["ordered_quantity"] or 0,
            "received_quantity": row["received_quantity"] or 0,
            "cancelled_quantity": row["cancelled_quantity"] or 0,
            "amount": "",
        }
        for row in line_rows
    )
    rows.extend(
        {
            "section": "invoice",
            "status": row["match_status"],
            "count": row["invoice_count"],
            "ordered_quantity": "",
            "received_quantity": "",
            "cancelled_quantity": "",
            "amount": row["total_amount"] or Decimal("0"),
        }
        for row in invoice_rows
    )
    return {
        "columns": _columns(
            "section",
            "status",
            "count",
            "ordered_quantity",
            "received_quantity",
            "cancelled_quantity",
            "amount",
        ),
        "rows": rows,
        "summary": {
            "orders": AcquisitionOrder.objects.count(),
            "order_lines": AcquisitionOrderLine.objects.count(),
            "invoices": Invoice.objects.count(),
        },
    }


def _serials_issue_exceptions(parameters: dict[str, Any]) -> dict[str, Any]:
    today = timezone.localdate()
    issues = (
        Issue.objects.filter(status=Issue.Status.MISSING)
        | Issue.objects.filter(status=Issue.Status.EXPECTED, expected_at__lt=today)
        | Issue.objects.filter(claim_count__gt=0)
    )
    issues = issues.select_related("serial_title", "subscription").order_by(
        "expected_at", "created_at"
    )[: int(parameters.get("limit") or 100)]
    rows = [
        {
            "issue_id": str(issue.id),
            "title": issue.serial_title.title,
            "enumeration": issue.enumeration,
            "chronology": issue.chronology,
            "expected_at": issue.expected_at,
            "status": issue.status,
            "claim_count": issue.claim_count,
        }
        for issue in issues
    ]
    return {
        "columns": _columns(
            "issue_id",
            "title",
            "enumeration",
            "chronology",
            "expected_at",
            "status",
            "claim_count",
        ),
        "rows": rows,
        "summary": {"exception_count": len(rows)},
    }


def _erm_expiring_resources(parameters: dict[str, Any]) -> dict[str, Any]:
    days = int(parameters.get("days") or 30)
    today = timezone.localdate()
    cutoff = today + timezone.timedelta(days=days)
    rows = []
    for license_obj in License.objects.filter(ends_at__gte=today, ends_at__lte=cutoff).order_by(
        "ends_at"
    ):
        rows.append(
            {
                "resource_type": "license",
                "name": license_obj.name,
                "status": license_obj.status,
                "ends_at": license_obj.ends_at,
                "vendor": _empty(license_obj.vendor),
                "days_remaining": (license_obj.ends_at - today).days if license_obj.ends_at else "",
            }
        )
    for package in Package.objects.filter(ends_at__gte=today, ends_at__lte=cutoff).order_by(
        "ends_at"
    ):
        rows.append(
            {
                "resource_type": "package",
                "name": package.name,
                "status": package.status,
                "ends_at": package.ends_at,
                "vendor": _empty(package.vendor),
                "days_remaining": (package.ends_at - today).days if package.ends_at else "",
            }
        )
    rows.extend(
        {
            "resource_type": "electronic_resource",
            "name": resource.title,
            "status": resource.status,
            "ends_at": "",
            "vendor": "",
            "days_remaining": "",
        }
        for resource in ElectronicResource.objects.filter(
            status=ElectronicResource.Status.TRIAL
        ).order_by("title")
    )
    return {
        "columns": _columns(
            "resource_type",
            "name",
            "status",
            "ends_at",
            "vendor",
            "days_remaining",
        ),
        "rows": rows,
        "summary": {"days": days, "expiring_count": len(rows)},
    }


def _cataloging_marc_import_errors(parameters: dict[str, Any]) -> dict[str, Any]:
    limit = int(parameters.get("limit") or 100)
    batch_rows = list(
        MarcImportBatch.objects.filter(invalid_count__gt=0)
        .values("id", "filename", "source", "status", "invalid_count", "conflict_count")
        .order_by("-created_at")[:limit]
    )
    records = (
        MarcImportRecord.objects.filter(
            status__in=[MarcImportRecord.Status.INVALID, MarcImportRecord.Status.CONFLICT]
        )
        .select_related("batch")
        .order_by("-created_at")[:limit]
    )
    rows = [
        {
            "record_type": "batch",
            "batch": str(row["id"]),
            "filename": row["filename"],
            "sequence": "",
            "control_number": "",
            "status": row["status"],
            "message": f"invalid={row['invalid_count']}, conflict={row['conflict_count']}",
        }
        for row in batch_rows
    ]
    rows.extend(
        {
            "record_type": "record",
            "batch": str(record.batch_id),
            "filename": record.batch.filename,
            "sequence": record.sequence,
            "control_number": record.control_number,
            "status": record.status,
            "message": record.conflict_reason
            or "; ".join(str(error) for error in record.validation_errors),
        }
        for record in records
    )
    return {
        "columns": _columns(
            "record_type",
            "batch",
            "filename",
            "sequence",
            "control_number",
            "status",
            "message",
        ),
        "rows": rows,
        "summary": {"issue_count": len(rows)},
    }


def _repository_digital_object_summary(parameters: dict[str, Any]) -> dict[str, Any]:
    rows = []
    object_counts = DigitalObject.objects.values("status").annotate(count=Count("id"))
    for row in object_counts.order_by("status"):
        rows.append(
            {
                "section": "digital_object",
                "category": row["status"],
                "sub_category": "",
                "count": row["count"],
            }
        )
    mime_access_counts = defaultdict(int)
    for row in FileAsset.objects.values("mime_type", "access_level").annotate(count=Count("id")):
        mime_access_counts[(row["mime_type"] or "(blank)", row["access_level"])] += row["count"]
    rows.extend(
        {
            "section": "file_asset",
            "category": mime_type,
            "sub_category": access_level,
            "count": count,
        }
        for (mime_type, access_level), count in sorted(mime_access_counts.items())
    )
    return {
        "columns": _columns("section", "category", "sub_category", "count"),
        "rows": rows,
        "summary": {
            "digital_objects": DigitalObject.objects.count(),
            "file_assets": FileAsset.objects.count(),
        },
    }
