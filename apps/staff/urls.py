from django.urls import path

from . import views

app_name = "staff"

urlpatterns = [
    path("analytics/", views.analytics_dashboard, name="analytics_dashboard"),
    path(
        "analytics/reports/<str:code>/",
        views.analytics_report_detail,
        name="analytics_report_detail",
    ),
    path(
        "analytics/reports/<str:code>/run/",
        views.analytics_report_run,
        name="analytics_report_run",
    ),
    path(
        "analytics/runs/<uuid:run_id>/",
        views.analytics_run_detail,
        name="analytics_run_detail",
    ),
    path(
        "analytics/runs/<uuid:run_id>/download/",
        views.analytics_run_download,
        name="analytics_run_download",
    ),
    path("audit/", views.audit_log_list, name="audit_log_list"),
    path("audit/export.csv", views.audit_log_export, name="audit_log_export"),
    path("audit/<int:audit_log_id>/", views.audit_log_detail, name="audit_log_detail"),
    path("data-quality/", views.data_quality_dashboard, name="data_quality_dashboard"),
    path("data-quality/run/", views.data_quality_run, name="data_quality_run"),
    path("exports/", views.export_job_list, name="export_job_list"),
    path("exports/<uuid:job_id>/download/", views.export_job_download, name="export_job_download"),
    path("repository/", views.repository_object_list, name="repository_object_list"),
    path("repository/new/", views.repository_object_new, name="repository_object_new"),
    path(
        "repository/<uuid:object_id>/",
        views.repository_object_detail,
        name="repository_object_detail",
    ),
    path(
        "repository/<uuid:object_id>/publish/",
        views.repository_object_publish,
        name="repository_object_publish",
    ),
    path(
        "repository/<uuid:object_id>/withdraw/",
        views.repository_object_withdraw,
        name="repository_object_withdraw",
    ),
    path(
        "repository/<uuid:object_id>/files/",
        views.repository_file_upload,
        name="repository_file_upload",
    ),
    path("circulation/", views.circulation_desk, name="circulation_desk"),
    path("circulation/checkout/", views.circulation_checkout, name="circulation_checkout"),
    path("circulation/return/", views.circulation_return, name="circulation_return"),
    path(
        "circulation/loans/<uuid:loan_id>/renew/", views.circulation_renew, name="circulation_renew"
    ),
    path("circulation/fees/", views.fee_list, name="fee_list"),
    path("circulation/payments/", views.payment_list, name="payment_list"),
    path("circulation/fees/<uuid:fine_fee_id>/waive/", views.fee_waive, name="fee_waive"),
    path("circulation/reports/", views.circulation_reports, name="circulation_reports"),
    path("patrons/", views.patron_list, name="patron_list"),
    path("patrons/new/", views.patron_new, name="patron_new"),
    path("patrons/<uuid:patron_id>/", views.patron_detail, name="patron_detail"),
    path("patrons/<uuid:patron_id>/edit/", views.patron_edit, name="patron_edit"),
    path("patrons/<uuid:patron_id>/fees/", views.patron_add_fee, name="patron_add_fee"),
    path(
        "patrons/<uuid:patron_id>/payments/",
        views.patron_record_payment,
        name="patron_record_payment",
    ),
    path("acquisitions/requests/", views.acquisition_request_list, name="acquisition_request_list"),
    path("acquisitions/orders/", views.acquisition_order_list, name="acquisition_order_list"),
    path(
        "acquisitions/orders/<uuid:order_id>/",
        views.acquisition_order_detail,
        name="acquisition_order_detail",
    ),
    path(
        "acquisitions/orders/<uuid:order_id>/place/",
        views.acquisition_order_place,
        name="acquisition_order_place",
    ),
    path(
        "acquisitions/receive/<uuid:line_id>/",
        views.acquisition_receive_line,
        name="acquisition_receive_line",
    ),
    path("acquisitions/invoices/", views.invoice_list, name="invoice_list"),
    path(
        "acquisitions/invoices/<uuid:invoice_id>/match/", views.invoice_match, name="invoice_match"
    ),
    path("acquisitions/funds/", views.fund_list, name="fund_list"),
    path("erm/resources/", views.erm_resource_list, name="erm_resource_list"),
    path(
        "erm/resources/<uuid:resource_id>/", views.erm_resource_detail, name="erm_resource_detail"
    ),
    path("erm/licenses/", views.erm_license_list, name="erm_license_list"),
    path("erm/licenses/<uuid:license_id>/", views.erm_license_detail, name="erm_license_detail"),
    path("erm/platforms/", views.erm_platform_list, name="erm_platform_list"),
    path("erm/packages/", views.erm_package_list, name="erm_package_list"),
    path("erm/expiring/", views.erm_expiry_list, name="erm_expiry_list"),
    path("serials/", views.serial_list, name="serial_list"),
    path(
        "serials/subscriptions/<uuid:subscription_id>/",
        views.subscription_detail,
        name="subscription_detail",
    ),
    path(
        "serials/subscriptions/<uuid:subscription_id>/generate/",
        views.subscription_generate_issues,
        name="subscription_generate_issues",
    ),
    path("serials/issues/<uuid:issue_id>/check-in/", views.issue_check_in, name="issue_check_in"),
    path(
        "serials/issues/<uuid:issue_id>/missing/",
        views.issue_mark_missing,
        name="issue_mark_missing",
    ),
    path("serials/issues/<uuid:issue_id>/claim/", views.issue_claim, name="issue_claim"),
    path("serials/bind/", views.issue_bind, name="issue_bind"),
    path("authorities/", views.authority_list, name="authority_list"),
    path("authorities/new/", views.authority_new, name="authority_new"),
    path("authorities/<uuid:authority_id>/", views.authority_detail, name="authority_detail"),
    path(
        "authorities/<uuid:authority_id>/access-points/",
        views.authority_add_access_point,
        name="authority_add_access_point",
    ),
    path(
        "authorities/<uuid:authority_id>/relations/",
        views.authority_add_relation,
        name="authority_add_relation",
    ),
    path("authorities/<uuid:authority_id>/merge/", views.authority_merge, name="authority_merge"),
    path(
        "authorities/<uuid:authority_id>/deprecate/",
        views.authority_deprecate,
        name="authority_deprecate",
    ),
    path("cataloging/imports/", views.import_batch_list, name="import_batch_list"),
    path("cataloging/imports/new/", views.import_batch_new, name="import_batch_new"),
    path(
        "cataloging/imports/<uuid:batch_id>/", views.import_batch_detail, name="import_batch_detail"
    ),
    path(
        "cataloging/imports/<uuid:batch_id>/parse/",
        views.import_batch_parse,
        name="import_batch_parse",
    ),
    path(
        "cataloging/import-records/<uuid:record_id>/review/",
        views.import_record_review,
        name="import_record_review",
    ),
    path(
        "cataloging/import-records/<uuid:record_id>/approve/",
        views.import_record_approve,
        name="import_record_approve",
    ),
    path(
        "cataloging/import-records/<uuid:record_id>/resolve/",
        views.import_record_resolve,
        name="import_record_resolve",
    ),
    path(
        "cataloging/import-records/<uuid:record_id>/reject/",
        views.import_record_reject,
        name="import_record_reject",
    ),
    path(
        "cataloging/authority-suggestions/<uuid:suggestion_id>/accept/",
        views.authority_suggestion_accept,
        name="authority_suggestion_accept",
    ),
    path(
        "cataloging/authority-suggestions/<uuid:suggestion_id>/create-provisional/",
        views.authority_suggestion_create_provisional,
        name="authority_suggestion_create_provisional",
    ),
    path(
        "cataloging/authority-suggestions/<uuid:suggestion_id>/reject/",
        views.authority_suggestion_reject,
        name="authority_suggestion_reject",
    ),
]
