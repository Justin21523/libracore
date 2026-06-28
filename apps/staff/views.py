from decimal import Decimal

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.acquisitions.models import (
    AcquisitionOrder,
    AcquisitionOrderLine,
    Fund,
    Invoice,
    PurchaseRequest,
)
from apps.acquisitions.services import (
    AcquisitionError,
    match_invoice,
    place_order,
    receive_order_line,
)
from apps.acquisitions.services import (
    ActorContext as AcquisitionActorContext,
)
from apps.analytics.models import ReportRun
from apps.analytics.services import (
    ReportPermissionError,
    UnknownReportError,
    can_run_report,
    run_report,
    visible_report_definitions,
)
from apps.authorities.models import AccessPoint, AuthorityRecord, AuthorityRelation
from apps.authorities.services import (
    AuthorityError,
    add_access_point,
    add_authority_relation,
    create_authority,
    deprecate_authority,
    merge_authorities,
)
from apps.catalog.models import BibliographicRecord, InstanceContributor, WorkAuthorityLink
from apps.circulation.models import FineFee, HoldRequest, Loan, Patron, Payment
from apps.circulation.services import (
    ActorContext as CirculationActorContext,
)
from apps.circulation.services import (
    CirculationError,
    checkout_item,
    record_payment,
    renew_loan,
    return_item,
    waive_fee,
)
from apps.core.audit import audit_logs_csv, filtered_audit_logs, json_diff, write_audit_log
from apps.core.data_quality import run_data_quality_checks
from apps.core.models import AuditLog, DataQualityRun
from apps.core.permissions import role_required
from apps.core.roles import (
    ROLE_ACQUISITIONS,
    ROLE_ADMIN,
    ROLE_CATALOGER,
    ROLE_CIRCULATION,
    ROLE_ERM,
    ROLE_REPOSITORY,
)
from apps.erm.models import ElectronicResource, License, Package, Platform
from apps.erm.services import (
    licenses_due_for_notice,
    package_expiry_queryset,
    public_access_links,
    resource_coverage_statements,
)
from apps.holdings.models import Branch, Item
from apps.interop.models import ExportJob
from apps.interop.services import create_and_run_export_job, export_content_type
from apps.marc.models import MarcImportBatch, MarcImportRecord
from apps.marc.review_services import (
    ActorContext,
    CatalogingError,
    accept_authority_suggestion,
    approve_import_record,
    create_import_batch,
    create_provisional_authority_from_suggestion,
    parse_import_batch,
    reject_authority_suggestion,
    reject_import_record,
    resolve_import_record,
)
from apps.notifications.models import Notification
from apps.repository.models import DigitalObject, FileAsset
from apps.repository.services import enrich_uploaded_asset, publish_object, withdraw_object
from apps.serials.models import Issue, SerialTitle, Subscription
from apps.serials.services import (
    ActorContext as SerialActorContext,
)
from apps.serials.services import (
    SerialError,
    bind_issues,
    check_in_issue,
    claim_issue,
    generate_expected_issues,
    mark_issue_missing,
)


def _actor_context(request) -> ActorContext:
    return ActorContext(
        actor=request.user,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


def _acq_context(request) -> AcquisitionActorContext:
    return AcquisitionActorContext(
        actor=request.user,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


def _serial_context(request) -> SerialActorContext:
    return SerialActorContext(
        actor=request.user,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


def _circ_context(request) -> CirculationActorContext:
    return CirculationActorContext(
        actor=request.user,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


def _request_audit_kwargs(request):
    return {
        "actor": request.user,
        "ip_address": request.META.get("REMOTE_ADDR"),
        "user_agent": request.META.get("HTTP_USER_AGENT", ""),
    }


@staff_member_required
def analytics_dashboard(request):
    reports = visible_report_definitions(request.user)
    recent_runs = (
        ReportRun.objects.filter(code__in=[report.code for report in reports])
        .select_related("requested_by")
        .order_by("-created_at")[:20]
    )
    return render(
        request,
        "staff/analytics/dashboard.html",
        {"reports": reports, "recent_runs": recent_runs},
    )


@staff_member_required
def analytics_report_detail(request, code):
    if not can_run_report(request.user, code):
        raise PermissionDenied("Required staff role is missing.")
    report = next(
        (
            definition
            for definition in visible_report_definitions(request.user)
            if definition.code == code
        ),
        None,
    )
    if not report:
        raise PermissionDenied("Required staff role is missing.")
    recent_runs = ReportRun.objects.filter(code=code).select_related("requested_by")[:20]
    return render(
        request,
        "staff/analytics/report_detail.html",
        {"report": report, "recent_runs": recent_runs},
    )


@staff_member_required
def analytics_report_run(request, code):
    if request.method != "POST":
        return redirect("staff:analytics_report_detail", code=code)
    parameters = {
        key: value
        for key, value in {
            "date_from": request.POST.get("date_from", "").strip(),
            "date_to": request.POST.get("date_to", "").strip(),
            "days": request.POST.get("days", "").strip(),
            "limit": request.POST.get("limit", "").strip(),
        }.items()
        if value
    }
    try:
        report_run = run_report(code, parameters=parameters, actor=request.user)
    except (ReportPermissionError, UnknownReportError) as exc:
        messages.error(request, str(exc))
        return redirect("staff:analytics_dashboard")
    if report_run.status == ReportRun.Status.COMPLETED:
        messages.success(request, f"報表已完成，共 {report_run.record_count} 筆。")
    else:
        messages.error(request, report_run.error_report or "報表執行失敗。")
    return redirect("staff:analytics_run_detail", run_id=report_run.id)


@staff_member_required
def analytics_run_detail(request, run_id):
    allowed_codes = {report.code for report in visible_report_definitions(request.user)}
    report_run = get_object_or_404(
        ReportRun.objects.select_related("requested_by", "report_definition"),
        id=run_id,
        code__in=allowed_codes,
    )
    return render(request, "staff/analytics/run_detail.html", {"run": report_run})


@staff_member_required
def analytics_run_download(request, run_id):
    allowed_codes = {report.code for report in visible_report_definitions(request.user)}
    report_run = get_object_or_404(ReportRun, id=run_id, code__in=allowed_codes)
    if report_run.status != ReportRun.Status.COMPLETED or not report_run.csv_file:
        messages.error(request, "報表 CSV 尚不可下載。")
        return redirect("staff:analytics_run_detail", run_id=report_run.id)
    return FileResponse(
        report_run.csv_file.open("rb"),
        as_attachment=True,
        filename=report_run.csv_file.name.rsplit("/", 1)[-1],
        content_type="text/csv",
    )


@staff_member_required
@role_required(ROLE_ADMIN)
def audit_log_list(request):
    logs = filtered_audit_logs(request.GET)[:200]
    return render(
        request,
        "staff/audit/list.html",
        {
            "logs": logs,
            "filters": {
                "actor": request.GET.get("actor", ""),
                "action": request.GET.get("action", ""),
                "entity_type": request.GET.get("entity_type", ""),
                "date_from": request.GET.get("date_from", ""),
                "date_to": request.GET.get("date_to", ""),
            },
        },
    )


@staff_member_required
@role_required(ROLE_ADMIN)
def audit_log_detail(request, audit_log_id):
    log = get_object_or_404(
        AuditLog.objects.select_related("actor", "entity_type"), id=audit_log_id
    )
    return render(
        request,
        "staff/audit/detail.html",
        {"log": log, "diff": json_diff(log.before, log.after)},
    )


@staff_member_required
@role_required(ROLE_ADMIN)
def audit_log_export(request):
    response = HttpResponse(
        audit_logs_csv(filtered_audit_logs(request.GET)),
        content_type="text/csv",
    )
    response["Content-Disposition"] = 'attachment; filename="audit-logs.csv"'
    return response


@staff_member_required
@role_required(ROLE_ADMIN)
def data_quality_dashboard(request):
    runs = DataQualityRun.objects.select_related("started_by").prefetch_related("issues")[:20]
    selected_run = runs[0] if runs else None
    issues = selected_run.issues.select_related("entity_type")[:200] if selected_run else []
    return render(
        request,
        "staff/data_quality/dashboard.html",
        {"runs": runs, "selected_run": selected_run, "issues": issues},
    )


@staff_member_required
@role_required(ROLE_ADMIN)
def data_quality_run(request):
    run = run_data_quality_checks(actor=request.user)
    messages.success(request, f"資料品質檢查完成，發現 {run.issue_count} 個問題。")
    return redirect("staff:data_quality_dashboard")


@staff_member_required
@role_required(ROLE_ADMIN)
def export_job_list(request):
    if request.method == "POST":
        job = create_and_run_export_job(
            export_type=request.POST["export_type"],
            requested_by=request.user,
            parameters={},
        )
        write_audit_log(
            action="export_job_created",
            entity=job,
            after={"export_type": job.export_type, "status": job.status},
            **_request_audit_kwargs(request),
        )
        messages.success(request, f"匯出完成：{job.export_type}，{job.record_count} 筆。")
        return redirect("staff:export_job_list")
    return render(
        request,
        "staff/exports/list.html",
        {
            "jobs": ExportJob.objects.select_related("requested_by")[:100],
            "export_types": ExportJob.ExportType.choices,
        },
    )


@staff_member_required
@role_required(ROLE_ADMIN)
def export_job_download(request, job_id):
    job = get_object_or_404(ExportJob, id=job_id)
    if job.status != ExportJob.Status.COMPLETED or not job.result_file:
        messages.error(request, "匯出檔尚不可下載。")
        return redirect("staff:export_job_list")
    return FileResponse(
        job.result_file.open("rb"),
        as_attachment=True,
        filename=job.result_file.name.rsplit("/", 1)[-1],
        content_type=export_content_type(job),
    )


@staff_member_required
@role_required(ROLE_REPOSITORY)
def repository_object_list(request):
    objects = (
        DigitalObject.objects.select_related(
            "bibliographic_record", "bibliographic_record__instance"
        )
        .prefetch_related("file_assets")
        .order_by("-created_at")[:100]
    )
    return render(request, "staff/repository/list.html", {"objects": objects})


@staff_member_required
@role_required(ROLE_REPOSITORY)
def repository_object_new(request):
    return _repository_object_form(request)


@staff_member_required
@role_required(ROLE_REPOSITORY)
def repository_object_detail(request, object_id):
    obj = get_object_or_404(
        DigitalObject.objects.select_related(
            "bibliographic_record", "bibliographic_record__instance"
        ).prefetch_related("file_assets"),
        id=object_id,
    )
    if request.method == "POST":
        return _repository_object_form(request, obj)
    return render(
        request,
        "staff/repository/detail.html",
        {
            "object": obj,
            "bib_records": BibliographicRecord.objects.select_related("instance")[:200],
            "statuses": DigitalObject.Status.choices,
        },
    )


@staff_member_required
@role_required(ROLE_REPOSITORY)
def repository_object_publish(request, object_id):
    obj = get_object_or_404(DigitalObject, id=object_id)
    publish_object(obj, **_request_audit_kwargs(request))
    messages.success(request, "數位物件已發布。")
    return redirect("staff:repository_object_detail", object_id=obj.id)


@staff_member_required
@role_required(ROLE_REPOSITORY)
def repository_object_withdraw(request, object_id):
    obj = get_object_or_404(DigitalObject, id=object_id)
    withdraw_object(obj, **_request_audit_kwargs(request))
    messages.success(request, "數位物件已撤回。")
    return redirect("staff:repository_object_detail", object_id=obj.id)


@staff_member_required
@role_required(ROLE_REPOSITORY)
def repository_file_upload(request, object_id):
    obj = get_object_or_404(DigitalObject, id=object_id)
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, "請選擇檔案。")
        return redirect("staff:repository_object_detail", object_id=obj.id)
    asset = FileAsset.objects.create(
        digital_object=obj,
        file=upload,
        label=request.POST.get("label", ""),
        access_level=request.POST.get("access_level", "public"),
        mime_type=request.POST.get("mime_type", ""),
        ocr_text=request.POST.get("ocr_text", ""),
    )
    enrich_uploaded_asset(asset, **_request_audit_kwargs(request))
    messages.success(request, "檔案已上傳。")
    return redirect("staff:repository_object_detail", object_id=obj.id)


def _repository_object_form(request, obj: DigitalObject | None = None):
    if request.method == "POST":
        metadata = _dc_metadata_from_post(request.POST)
        values = {
            "title": request.POST["title"].strip(),
            "bibliographic_record_id": request.POST.get("bibliographic_record_id") or None,
            "dc_metadata": metadata,
            "rights_statement": request.POST.get("rights_statement", ""),
            "status": request.POST.get("status", DigitalObject.Status.DRAFT),
            "oai_identifier": request.POST.get("oai_identifier", ""),
        }
        if obj:
            before = {"title": obj.title, "status": obj.status, "dc_metadata": obj.dc_metadata}
            for key, value in values.items():
                setattr(obj, key, value)
            obj.save()
            write_audit_log(
                action="digital_object_staff_updated",
                entity=obj,
                before=before,
                after={"title": obj.title, "status": obj.status, "dc_metadata": obj.dc_metadata},
                **_request_audit_kwargs(request),
            )
            messages.success(request, "數位物件已更新。")
        else:
            obj = DigitalObject.objects.create(**values)
            write_audit_log(
                action="digital_object_staff_created",
                entity=obj,
                after={"title": obj.title, "status": obj.status, "dc_metadata": obj.dc_metadata},
                **_request_audit_kwargs(request),
            )
            messages.success(request, "數位物件已建立。")
        return redirect("staff:repository_object_detail", object_id=obj.id)
    return render(
        request,
        "staff/repository/form.html",
        {
            "object": obj,
            "bib_records": BibliographicRecord.objects.select_related("instance")[:200],
            "statuses": DigitalObject.Status.choices,
        },
    )


def _dc_metadata_from_post(post) -> dict:
    metadata = {}
    for key in [
        "title",
        "creator",
        "subject",
        "description",
        "publisher",
        "contributor",
        "date",
        "type",
        "format",
        "identifier",
        "source",
        "language",
        "relation",
        "coverage",
        "rights",
        "collection",
    ]:
        value = post.get(f"dc_{key}", "").strip()
        if value:
            metadata[key] = [line.strip() for line in value.splitlines() if line.strip()]
            if len(metadata[key]) == 1:
                metadata[key] = metadata[key][0]
    return metadata


def _patron_summary_context(patron: Patron | None = None, item: Item | None = None) -> dict:
    open_fees = FineFee.objects.none()
    fee_balance = Decimal("0.00")
    block_reasons = []
    if patron:
        open_fees = patron.fees.filter(status=FineFee.Status.OPEN)
        fee_balance = open_fees.aggregate(total=Sum("balance_amount"))["total"] or Decimal("0.00")
        if patron.expiry_date and patron.expiry_date < timezone.localdate():
            block_reasons.append("讀者證已到期")
        if fee_balance > 0:
            block_reasons.append(f"未繳費用 {fee_balance}")
    return {
        "patron": patron,
        "item": item,
        "open_loans": patron.loans.filter(status=Loan.Status.OPEN).select_related(
            "item__holding__instance"
        )
        if patron
        else Loan.objects.none(),
        "holds": patron.hold_requests.select_related(
            "instance", "item__holding__instance", "pickup_location"
        )
        if patron
        else HoldRequest.objects.none(),
        "open_fees": open_fees,
        "fee_balance": fee_balance,
        "block_reasons": block_reasons,
    }


def _find_patron_by_barcode(value: str) -> Patron | None:
    value = (value or "").strip()
    if not value:
        return None
    return Patron.objects.select_related("user", "home_branch").filter(barcode=value).first()


def _find_item_by_barcode(value: str) -> Item | None:
    value = (value or "").strip()
    if not value:
        return None
    return (
        Item.objects.select_related(
            "holding", "holding__instance", "holding__branch", "holding__location"
        )
        .filter(barcode=value)
        .first()
    )


@staff_member_required
@role_required(ROLE_CIRCULATION)
def circulation_desk(request):
    patron = _find_patron_by_barcode(request.GET.get("patron_barcode", ""))
    item = _find_item_by_barcode(request.GET.get("item_barcode", ""))
    if request.GET.get("patron_barcode") and not patron:
        messages.error(request, "找不到讀者條碼。")
    if request.GET.get("item_barcode") and not item:
        messages.error(request, "找不到單冊條碼。")
    return render(request, "staff/circulation/desk.html", _patron_summary_context(patron, item))


@staff_member_required
@role_required(ROLE_CIRCULATION)
def circulation_checkout(request):
    patron = _find_patron_by_barcode(request.POST.get("patron_barcode", ""))
    item = _find_item_by_barcode(request.POST.get("item_barcode", ""))
    if not patron or not item:
        messages.error(request, "借出需要有效的讀者條碼與單冊條碼。")
        return redirect("staff:circulation_desk")
    try:
        loan = checkout_item(
            item_id=item.id, patron_id=patron.id, actor_context=_circ_context(request)
        )
        messages.success(request, f"借出完成，到期日 {timezone.localtime(loan.due_at).date()}。")
    except CirculationError as exc:
        messages.error(request, str(exc))
    return redirect(f"{request.META.get('HTTP_REFERER') or '/staff/circulation/'}")


@staff_member_required
@role_required(ROLE_CIRCULATION)
def circulation_return(request):
    item = _find_item_by_barcode(request.POST.get("item_barcode", ""))
    if not item:
        messages.error(request, "還書需要有效的單冊條碼。")
        return redirect("staff:circulation_desk")
    loan = Loan.objects.filter(item=item, status=Loan.Status.OPEN).select_related("item").first()
    if not loan:
        messages.error(request, "找不到此單冊的未歸還借閱。")
        return redirect("staff:circulation_desk")
    try:
        returned = return_item(loan_id=loan.id, actor_context=_circ_context(request))
        ready_hold = HoldRequest.objects.filter(
            item=returned.item, status=HoldRequest.Status.READY
        ).first()
        if ready_hold:
            expires_on = timezone.localtime(ready_hold.expires_at).date()
            messages.success(
                request,
                f"還書完成，已轉入待取，保留至 {expires_on}。",
            )
        else:
            messages.success(request, "還書完成。")
    except CirculationError as exc:
        messages.error(request, str(exc))
    return redirect("staff:circulation_desk")


@staff_member_required
@role_required(ROLE_CIRCULATION)
def circulation_renew(request, loan_id):
    try:
        loan = renew_loan(loan_id=loan_id, actor_context=_circ_context(request))
        messages.success(request, f"續借完成，新到期日 {timezone.localtime(loan.due_at).date()}。")
    except CirculationError as exc:
        messages.error(request, str(exc))
    return redirect(request.META.get("HTTP_REFERER") or "staff:circulation_desk")


@staff_member_required
@role_required(ROLE_CIRCULATION)
def patron_list(request):
    patrons = Patron.objects.select_related("user", "home_branch").order_by("barcode")
    query = request.GET.get("q", "").strip()
    if query:
        patrons = (
            patrons.filter(user__username__icontains=query)
            | patrons.filter(user__email__icontains=query)
            | patrons.filter(barcode__icontains=query)
        )
    return render(
        request, "staff/patrons/list.html", {"patrons": patrons.distinct()[:100], "query": query}
    )


@staff_member_required
@role_required(ROLE_CIRCULATION)
def patron_detail(request, patron_id):
    patron = get_object_or_404(Patron.objects.select_related("user", "home_branch"), id=patron_id)
    return render(
        request,
        "staff/patrons/detail.html",
        {
            "patron": patron,
            "loans": patron.loans.select_related("item__holding__instance").order_by(
                "-checked_out_at"
            )[:100],
            "holds": patron.hold_requests.select_related(
                "instance", "item__holding__instance", "pickup_location"
            ).order_by("-created_at")[:100],
            "fees": patron.fees.select_related("loan__item__holding__instance").order_by(
                "-created_at"
            )[:100],
            "payments": patron.payments.prefetch_related("allocations__fine_fee").order_by(
                "-received_at"
            )[:100],
            "notifications": Notification.objects.filter(recipient_user=patron.user).order_by(
                "-created_at"
            )[:100],
            "payment_methods": Payment.Method.choices,
        },
    )


@staff_member_required
@role_required(ROLE_CIRCULATION)
def patron_new(request):
    return _patron_form(request)


@staff_member_required
@role_required(ROLE_CIRCULATION)
def patron_edit(request, patron_id):
    patron = get_object_or_404(Patron, id=patron_id)
    return _patron_form(request, patron)


def _patron_form(request, patron: Patron | None = None):
    if request.method == "POST":
        try:
            user = get_user_model().objects.get(id=request.POST["user_id"])
            values = {
                "user": user,
                "barcode": request.POST["barcode"].strip(),
                "patron_type": request.POST.get("patron_type", "standard").strip() or "standard",
                "expiry_date": parse_date(request.POST.get("expiry_date", ""))
                if request.POST.get("expiry_date")
                else None,
                "privacy_opt_in": request.POST.get("privacy_opt_in") == "on",
                "home_branch_id": request.POST.get("home_branch_id") or None,
            }
            if patron:
                for key, value in values.items():
                    setattr(patron, key, value)
                patron.save()
                messages.success(request, "讀者資料已更新。")
            else:
                patron = Patron.objects.create(**values)
                messages.success(request, "讀者資料已建立。")
            return redirect("staff:patron_detail", patron_id=patron.id)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, str(exc))
    return render(
        request,
        "staff/patrons/form.html",
        {
            "patron": patron,
            "users": get_user_model().objects.order_by("username")[:200],
            "branches": Branch.objects.order_by("name"),
        },
    )


@staff_member_required
@role_required(ROLE_CIRCULATION)
def patron_add_fee(request, patron_id):
    patron = get_object_or_404(Patron, id=patron_id)
    try:
        amount = Decimal(str(request.POST["amount"])).quantize(Decimal("0.01"))
        FineFee.objects.create(
            patron=patron,
            fee_type=FineFee.FeeType.MANUAL,
            reason=request.POST.get("reason", "Manual fee"),
            amount=amount,
            original_amount=amount,
            balance_amount=amount,
            assessed_at=timezone.now(),
            note=request.POST.get("note", ""),
        )
        messages.success(request, "已新增手動費用。")
    except Exception as exc:  # noqa: BLE001
        messages.error(request, str(exc))
    return redirect("staff:patron_detail", patron_id=patron.id)


@staff_member_required
@role_required(ROLE_CIRCULATION)
def patron_record_payment(request, patron_id):
    patron = get_object_or_404(Patron, id=patron_id)
    try:
        record_payment(
            patron_id=patron.id,
            amount=request.POST["amount"],
            method=request.POST.get("method", Payment.Method.CASH),
            reference=request.POST.get("reference", ""),
            note=request.POST.get("note", ""),
            actor_context=_circ_context(request),
        )
        messages.success(request, "收款完成。")
    except (CirculationError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("staff:patron_detail", patron_id=patron.id)


@staff_member_required
@role_required(ROLE_CIRCULATION)
def fee_list(request):
    fees = FineFee.objects.select_related("patron__user", "loan__item__holding__instance").order_by(
        "-created_at"
    )[:100]
    return render(request, "staff/circulation/fee_list.html", {"fees": fees})


@staff_member_required
@role_required(ROLE_CIRCULATION)
def payment_list(request):
    payments = (
        Payment.objects.select_related("patron__user", "received_by")
        .prefetch_related("allocations__fine_fee")
        .order_by("-received_at")[:100]
    )
    return render(request, "staff/circulation/payment_list.html", {"payments": payments})


@staff_member_required
@role_required(ROLE_ADMIN)
def fee_waive(request, fine_fee_id):
    fee = get_object_or_404(FineFee, id=fine_fee_id)
    try:
        waive_fee(
            fine_fee_id=fee.id,
            amount=request.POST["amount"],
            reason=request.POST.get("reason", "Staff waiver"),
            actor_context=_circ_context(request),
        )
        messages.success(request, "費用減免完成。")
    except (CirculationError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect(request.META.get("HTTP_REFERER") or "staff:fee_list")


@staff_member_required
@role_required(ROLE_CIRCULATION)
def circulation_reports(request):
    today = timezone.localdate()
    start = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
    end = start + timezone.timedelta(days=1)
    high_balance_threshold = Decimal("1000.00")
    high_balance_patrons = (
        Patron.objects.filter(fees__status=FineFee.Status.OPEN)
        .select_related("user")
        .annotate(open_balance=Sum("fees__balance_amount"))
        .filter(open_balance__gte=high_balance_threshold)
        .order_by("-open_balance")[:100]
    )
    return render(
        request,
        "staff/circulation/reports.html",
        {
            "today_checkouts": Loan.objects.filter(
                checked_out_at__gte=start, checked_out_at__lt=end
            ).select_related("patron__user", "item")[:100],
            "today_returns": Loan.objects.filter(
                returned_at__gte=start, returned_at__lt=end
            ).select_related("patron__user", "item")[:100],
            "overdue_loans": Loan.objects.filter(
                status=Loan.Status.OPEN, due_at__lt=timezone.now()
            ).select_related("patron__user", "item__holding__instance")[:100],
            "ready_holds": HoldRequest.objects.filter(
                status=HoldRequest.Status.READY
            ).select_related(
                "patron__user", "instance", "item__holding__instance", "pickup_location"
            )[:100],
            "high_balance_patrons": high_balance_patrons,
            "problem_items": Item.objects.filter(
                status__in=[Item.Status.MISSING, Item.Status.LOST]
            ).select_related("holding__instance", "holding__location")[:100],
        },
    )


@staff_member_required
@role_required(ROLE_ACQUISITIONS)
def acquisition_request_list(request):
    requests = PurchaseRequest.objects.select_related("vendor", "requester").order_by(
        "-created_at"
    )[:100]
    return render(request, "staff/acquisitions/request_list.html", {"requests": requests})


@staff_member_required
@role_required(ROLE_ACQUISITIONS)
def acquisition_order_list(request):
    orders = AcquisitionOrder.objects.select_related("vendor").order_by("-created_at")[:100]
    return render(request, "staff/acquisitions/order_list.html", {"orders": orders})


@staff_member_required
@role_required(ROLE_ACQUISITIONS)
def acquisition_order_detail(request, order_id):
    order = get_object_or_404(
        AcquisitionOrder.objects.select_related("vendor").prefetch_related("lines"), id=order_id
    )
    return render(request, "staff/acquisitions/order_detail.html", {"order": order})


@staff_member_required
@role_required(ROLE_ACQUISITIONS)
def acquisition_order_place(request, order_id):
    try:
        place_order(order_id=order_id, actor_context=_acq_context(request))
        messages.success(request, "訂單已下訂。")
    except AcquisitionError as exc:
        messages.error(request, str(exc))
    return redirect("staff:acquisition_order_detail", order_id=order_id)


@staff_member_required
@role_required(ROLE_ACQUISITIONS)
def acquisition_receive_line(request, line_id):
    line = get_object_or_404(
        AcquisitionOrderLine.objects.select_related("order", "branch", "location"), id=line_id
    )
    if request.method == "POST":
        barcodes = [
            value.strip()
            for value in request.POST.get("barcodes", "").splitlines()
            if value.strip()
        ]
        try:
            receive_order_line(
                order_line_id=line.id,
                quantity=int(request.POST.get("quantity", len(barcodes))),
                barcodes=barcodes,
                actor_context=_acq_context(request),
            )
            messages.success(request, "驗收完成。")
            return redirect("staff:acquisition_order_detail", order_id=line.order_id)
        except (AcquisitionError, ValueError) as exc:
            messages.error(request, str(exc))
    return render(request, "staff/acquisitions/receive_line.html", {"line": line})


@staff_member_required
@role_required(ROLE_ACQUISITIONS)
def invoice_list(request):
    invoices = Invoice.objects.select_related("vendor", "order").order_by("-created_at")[:100]
    return render(request, "staff/acquisitions/invoice_list.html", {"invoices": invoices})


@staff_member_required
@role_required(ROLE_ACQUISITIONS)
def invoice_match(request, invoice_id):
    try:
        match_invoice(invoice_id=invoice_id, actor_context=_acq_context(request))
        messages.success(request, "發票對帳完成。")
    except AcquisitionError as exc:
        messages.error(request, str(exc))
    return redirect("staff:invoice_list")


@staff_member_required
@role_required(ROLE_ACQUISITIONS)
def fund_list(request):
    funds = Fund.objects.prefetch_related("transactions").order_by("code")
    return render(request, "staff/acquisitions/fund_list.html", {"funds": funds})


@staff_member_required
@role_required(ROLE_ERM)
def erm_resource_list(request):
    resources = (
        ElectronicResource.objects.select_related("platform_ref", "package", "license", "instance")
        .prefetch_related("access_urls", "coverages")
        .order_by("title")[:100]
    )
    return render(request, "staff/erm/resource_list.html", {"resources": resources})


@staff_member_required
@role_required(ROLE_ERM)
def erm_resource_detail(request, resource_id):
    resource = get_object_or_404(
        ElectronicResource.objects.select_related(
            "platform_ref", "package", "license", "instance"
        ).prefetch_related("access_urls__proxy_config", "coverages", "license__license_terms"),
        id=resource_id,
    )
    return render(
        request,
        "staff/erm/resource_detail.html",
        {
            "resource": resource,
            "access_links": public_access_links(resource),
            "coverage_statements": resource_coverage_statements(resource),
        },
    )


@staff_member_required
@role_required(ROLE_ERM)
def erm_license_list(request):
    licenses = (
        License.objects.select_related("vendor", "invoice")
        .prefetch_related("license_terms", "resources")
        .order_by("ends_at", "name")[:100]
    )
    return render(request, "staff/erm/license_list.html", {"licenses": licenses})


@staff_member_required
@role_required(ROLE_ERM)
def erm_license_detail(request, license_id):
    license_obj = get_object_or_404(
        License.objects.select_related("vendor", "invoice").prefetch_related(
            "license_terms", "resources__platform_ref", "packages"
        ),
        id=license_id,
    )
    return render(request, "staff/erm/license_detail.html", {"license": license_obj})


@staff_member_required
@role_required(ROLE_ERM)
def erm_platform_list(request):
    platforms = (
        Platform.objects.select_related("vendor")
        .prefetch_related("resources", "packages")
        .order_by("name")
    )
    return render(request, "staff/erm/platform_list.html", {"platforms": platforms})


@staff_member_required
@role_required(ROLE_ERM)
def erm_package_list(request):
    packages = (
        Package.objects.select_related("platform", "vendor", "license")
        .prefetch_related("resources")
        .order_by("name")
    )
    return render(request, "staff/erm/package_list.html", {"packages": packages})


@staff_member_required
@role_required(ROLE_ERM)
def erm_expiry_list(request):
    return render(
        request,
        "staff/erm/expiry_list.html",
        {
            "licenses": licenses_due_for_notice(),
            "packages": package_expiry_queryset()[:100],
        },
    )


@staff_member_required
@role_required(ROLE_ACQUISITIONS)
def serial_list(request):
    serials = SerialTitle.objects.prefetch_related("subscriptions", "issues").order_by("title")[
        :100
    ]
    return render(request, "staff/serials/list.html", {"serials": serials})


@staff_member_required
@role_required(ROLE_ACQUISITIONS)
def subscription_detail(request, subscription_id):
    subscription = get_object_or_404(
        Subscription.objects.select_related("serial_title", "branch", "location").prefetch_related(
            "issues"
        ),
        id=subscription_id,
    )
    return render(request, "staff/serials/subscription_detail.html", {"subscription": subscription})


@staff_member_required
@role_required(ROLE_ACQUISITIONS)
def subscription_generate_issues(request, subscription_id):
    try:
        generate_expected_issues(
            subscription_id=subscription_id,
            count=int(request.POST.get("count", "1")),
            actor_context=_serial_context(request),
        )
        messages.success(request, "已產生預期刊期。")
    except (SerialError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("staff:subscription_detail", subscription_id=subscription_id)


@staff_member_required
@role_required(ROLE_ACQUISITIONS)
def issue_check_in(request, issue_id):
    issue = get_object_or_404(Issue, id=issue_id)
    try:
        check_in_issue(issue_id=issue_id, actor_context=_serial_context(request))
        messages.success(request, "到刊 check-in 完成。")
    except SerialError as exc:
        messages.error(request, str(exc))
    return redirect("staff:subscription_detail", subscription_id=issue.subscription_id)


@staff_member_required
@role_required(ROLE_ACQUISITIONS)
def issue_mark_missing(request, issue_id):
    issue = get_object_or_404(Issue, id=issue_id)
    mark_issue_missing(issue_id=issue_id, actor_context=_serial_context(request))
    messages.success(request, "已標記缺期。")
    return redirect("staff:subscription_detail", subscription_id=issue.subscription_id)


@staff_member_required
@role_required(ROLE_ACQUISITIONS)
def issue_claim(request, issue_id):
    issue = get_object_or_404(Issue, id=issue_id)
    claim_issue(
        issue_id=issue_id, note=request.POST.get("note", ""), actor_context=_serial_context(request)
    )
    messages.success(request, "已建立催缺紀錄。")
    return redirect("staff:subscription_detail", subscription_id=issue.subscription_id)


@staff_member_required
@role_required(ROLE_ACQUISITIONS)
def issue_bind(request):
    if request.method == "POST":
        issue_ids = request.POST.getlist("issue_ids")
        try:
            bind_issues(
                issue_ids=issue_ids,
                label=request.POST["label"],
                actor_context=_serial_context(request),
            )
            messages.success(request, "已完成裝訂。")
        except (SerialError, KeyError) as exc:
            messages.error(request, str(exc))
    return redirect("staff:serial_list")


@staff_member_required
@role_required(ROLE_CATALOGER)
def authority_list(request):
    authorities = AuthorityRecord.objects.prefetch_related("access_points")
    if request.GET.get("q"):
        authorities = authorities.filter(access_points__label__icontains=request.GET["q"])
    if request.GET.get("authority_type"):
        authorities = authorities.filter(authority_type=request.GET["authority_type"])
    if request.GET.get("status"):
        authorities = authorities.filter(status=request.GET["status"])
    authorities = authorities.distinct().order_by("access_points__sort_key", "created_at")[:100]
    return render(
        request,
        "staff/authorities/list.html",
        {
            "authorities": authorities,
            "types": AuthorityRecord.AuthorityType.choices,
            "statuses": AuthorityRecord.Status.choices,
        },
    )


@staff_member_required
@role_required(ROLE_CATALOGER)
def authority_new(request):
    if request.method == "POST":
        try:
            authority = create_authority(
                authority_type=request.POST["authority_type"],
                preferred_label=request.POST["preferred_label"],
                source=request.POST.get("source", "local"),
                control_number=request.POST.get("control_number", ""),
                entity_uri=request.POST.get("entity_uri", ""),
                status=request.POST.get("status", AuthorityRecord.Status.PROVISIONAL),
                actor_context=_actor_context(request),
            )
            messages.success(request, "已建立權威紀錄。")
            return redirect("staff:authority_detail", authority_id=authority.id)
        except (AuthorityError, ValueError) as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "staff/authorities/new.html",
        {
            "types": AuthorityRecord.AuthorityType.choices,
            "statuses": AuthorityRecord.Status.choices,
        },
    )


@staff_member_required
@role_required(ROLE_CATALOGER)
def authority_detail(request, authority_id):
    authority = get_object_or_404(
        AuthorityRecord.objects.prefetch_related(
            "access_points",
            "external_identifiers",
            "outgoing_relations__target__access_points",
            "incoming_relations__source__access_points",
        ),
        id=authority_id,
    )
    work_ids = WorkAuthorityLink.objects.filter(authority=authority).values_list(
        "work_id", flat=True
    )
    instance_ids = InstanceContributor.objects.filter(authority=authority).values_list(
        "instance_id", flat=True
    )
    linked_records = (
        (
            BibliographicRecord.objects.filter(work_id__in=work_ids)
            | BibliographicRecord.objects.filter(instance_id__in=instance_ids)
        )
        .select_related("instance")
        .distinct()
    )
    return render(
        request,
        "staff/authorities/detail.html",
        {
            "authority": authority,
            "linked_records": linked_records,
            "access_point_kinds": AccessPoint.Kind.choices,
            "relation_types": AuthorityRelation.RelationType.choices,
            "all_authorities": AuthorityRecord.objects.exclude(id=authority.id)[:100],
        },
    )


@staff_member_required
@role_required(ROLE_CATALOGER)
def authority_add_access_point(request, authority_id):
    try:
        add_access_point(
            authority_id=authority_id,
            label=request.POST["label"],
            kind=request.POST.get("kind", AccessPoint.Kind.VARIANT),
            language=request.POST.get("language", ""),
            script=request.POST.get("script", ""),
            romanization=request.POST.get("romanization", ""),
            source_field=request.POST.get("source_field", ""),
            is_preferred=request.POST.get("is_preferred") == "on",
            actor_context=_actor_context(request),
        )
        messages.success(request, "已新增標目。")
    except (AuthorityError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("staff:authority_detail", authority_id=authority_id)


@staff_member_required
@role_required(ROLE_CATALOGER)
def authority_add_relation(request, authority_id):
    try:
        add_authority_relation(
            source_id=authority_id,
            target_id=request.POST["target_id"],
            relation_type=request.POST["relation_type"],
            note=request.POST.get("note", ""),
            actor_context=_actor_context(request),
        )
        messages.success(request, "已新增權威關係。")
    except (AuthorityError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("staff:authority_detail", authority_id=authority_id)


@staff_member_required
@role_required(ROLE_ADMIN)
def authority_merge(request, authority_id):
    if request.method == "POST":
        try:
            target = merge_authorities(
                source_id=authority_id,
                target_id=request.POST["target_id"],
                note=request.POST.get("note", ""),
                actor_context=_actor_context(request),
            )
            messages.success(request, "已合併權威紀錄。")
            return redirect("staff:authority_detail", authority_id=target.id)
        except (AuthorityError, ValueError) as exc:
            messages.error(request, str(exc))
    return redirect("staff:authority_detail", authority_id=authority_id)


@staff_member_required
@role_required(ROLE_ADMIN)
def authority_deprecate(request, authority_id):
    try:
        deprecate_authority(
            authority_id=authority_id,
            replacement_id=request.POST.get("replacement_id") or None,
            note=request.POST.get("note", ""),
            actor_context=_actor_context(request),
        )
        messages.success(request, "已標記權威為 deprecated。")
    except (AuthorityError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("staff:authority_detail", authority_id=authority_id)


@staff_member_required
@role_required(ROLE_CATALOGER)
def import_batch_list(request):
    batches = MarcImportBatch.objects.select_related("submitted_by").all()[:100]
    return render(request, "staff/cataloging/import_batch_list.html", {"batches": batches})


@staff_member_required
@role_required(ROLE_CATALOGER)
def import_batch_new(request):
    if request.method == "POST":
        upload = request.FILES.get("file")
        if not upload:
            messages.error(request, "請選擇 MARC 檔案。")
            return redirect("staff:import_batch_new")
        try:
            batch = create_import_batch(
                payload=upload.read(),
                import_format=request.POST["import_format"],
                source=request.POST.get("source", ""),
                filename=upload.name,
                actor_context=_actor_context(request),
            )
        except ValueError as exc:
            messages.error(request, f"匯入失敗：{exc}")
            return redirect("staff:import_batch_new")
        messages.success(request, "已建立 MARC 匯入批次。")
        return redirect("staff:import_batch_detail", batch_id=batch.id)
    return render(
        request,
        "staff/cataloging/import_batch_new.html",
        {"formats": MarcImportBatch.ImportFormat.choices},
    )


@staff_member_required
@role_required(ROLE_CATALOGER)
def import_batch_detail(request, batch_id):
    batch = get_object_or_404(MarcImportBatch.objects.select_related("submitted_by"), id=batch_id)
    records = batch.records.all().order_by("sequence")
    return render(
        request,
        "staff/cataloging/import_batch_detail.html",
        {"batch": batch, "records": records},
    )


@staff_member_required
@role_required(ROLE_CATALOGER)
def import_batch_parse(request, batch_id):
    try:
        parse_import_batch(batch_id=batch_id, actor_context=_actor_context(request))
        messages.success(request, "批次解析完成。")
    except CatalogingError as exc:
        messages.error(request, str(exc))
    return redirect("staff:import_batch_detail", batch_id=batch_id)


@staff_member_required
@role_required(ROLE_CATALOGER)
def import_record_review(request, record_id):
    record = get_object_or_404(
        MarcImportRecord.objects.select_related(
            "batch", "bibliographic_record", "authority_record", "holding", "marc_record"
        ).prefetch_related("match_candidates"),
        id=record_id,
    )
    suggestions = record.authority_suggestions.select_related("matched_authority").all()
    return render(
        request,
        "staff/cataloging/import_record_review.html",
        {
            "record": record,
            "suggestions": suggestions,
            "match_candidates": record.match_candidates.all(),
        },
    )


@staff_member_required
@role_required(ROLE_CATALOGER)
def import_record_approve(request, record_id):
    overrides = {}
    if request.method == "POST":
        overrides = _marc_overrides_from_post(request.POST)
    try:
        record = approve_import_record(
            import_record_id=record_id,
            mapped_overrides=overrides,
            actor_context=_actor_context(request),
        )
        messages.success(request, "已核准並建立正式書目。")
    except CatalogingError as exc:
        messages.error(request, str(exc))
        record = get_object_or_404(MarcImportRecord, id=record_id)
    return redirect("staff:import_record_review", record_id=record.id)


@staff_member_required
@role_required(ROLE_CATALOGER)
def import_record_resolve(request, record_id):
    overrides = {}
    if request.method == "POST":
        overrides = _marc_overrides_from_post(request.POST)
    try:
        record = resolve_import_record(
            import_record_id=record_id,
            action=request.POST.get("action", "create_new"),
            target_id=request.POST.get("target_id") or None,
            mapped_overrides=overrides,
            actor_context=_actor_context(request),
        )
        messages.success(request, "MARC 紀錄已解析入庫。")
    except CatalogingError as exc:
        messages.error(request, str(exc))
        record = get_object_or_404(MarcImportRecord, id=record_id)
    return redirect("staff:import_record_review", record_id=record.id)


def _marc_overrides_from_post(post) -> dict:
    overrides = {}
    for post_key, path in [
        ("work_primary_title", ("work", "primary_title")),
        ("instance_title_statement", ("instance", "title_statement")),
        ("publisher", ("instance", "publisher")),
        ("publication_date", ("instance", "publication_date")),
        ("authority_preferred_label", ("authority", "preferred_label")),
        ("holding_branch_code", ("holding", "branch_code")),
        ("holding_location_code", ("holding", "location_code")),
        ("holding_call_number", ("holding", "call_number")),
    ]:
        value = post.get(post_key, "").strip()
        if value:
            overrides.setdefault(path[0], {})[path[1]] = value
    return overrides


@staff_member_required
@role_required(ROLE_CATALOGER)
def import_record_reject(request, record_id):
    note = request.POST.get("note", "") if request.method == "POST" else ""
    try:
        record = reject_import_record(
            import_record_id=record_id,
            note=note,
            actor_context=_actor_context(request),
        )
        messages.success(request, "已拒收此筆紀錄。")
    except CatalogingError as exc:
        messages.error(request, str(exc))
        record = get_object_or_404(MarcImportRecord, id=record_id)
    return redirect("staff:import_record_review", record_id=record.id)


@staff_member_required
@role_required(ROLE_CATALOGER)
def authority_suggestion_create_provisional(request, suggestion_id):
    suggestion = create_provisional_authority_from_suggestion(
        suggestion_id=suggestion_id,
        actor_context=_actor_context(request),
    )
    messages.success(request, "已建立 provisional authority。")
    return redirect("staff:import_record_review", record_id=suggestion.import_record_id)


@staff_member_required
@role_required(ROLE_CATALOGER)
def authority_suggestion_accept(request, suggestion_id):
    authority_id = request.POST.get("authority_id")
    try:
        suggestion = accept_authority_suggestion(
            suggestion_id=suggestion_id,
            authority_id=authority_id,
            actor_context=_actor_context(request),
        )
        messages.success(request, "已接受權威候選並建立連結。")
    except CatalogingError as exc:
        messages.error(request, str(exc))
        suggestion = get_object_or_404(
            MarcImportRecord, authority_suggestions__id=suggestion_id
        ).authority_suggestions.get(id=suggestion_id)
    return redirect("staff:import_record_review", record_id=suggestion.import_record_id)


@staff_member_required
@role_required(ROLE_CATALOGER)
def authority_suggestion_reject(request, suggestion_id):
    suggestion = reject_authority_suggestion(
        suggestion_id=suggestion_id,
        note=request.POST.get("note", ""),
        actor_context=_actor_context(request),
    )
    messages.success(request, "已拒絕權威候選。")
    return redirect("staff:import_record_review", record_id=suggestion.import_record_id)
