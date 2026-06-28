from django.urls import path

from . import views

app_name = "discovery"

urlpatterns = [
    path("", views.search_home, name="home"),
    path("search/", views.search_results, name="search"),
    path("account/", views.account_dashboard, name="account_dashboard"),
    path("account/loans/", views.account_loans, name="account_loans"),
    path("account/holds/", views.account_holds, name="account_holds"),
    path("account/fees/", views.account_fees, name="account_fees"),
    path("account/notifications/", views.account_notifications, name="account_notifications"),
    path(
        "account/notifications/<uuid:notification_id>/read/",
        views.account_notification_mark_read,
        name="account_notification_mark_read",
    ),
    path(
        "account/loans/<uuid:loan_id>/renew/", views.account_renew_loan, name="account_renew_loan"
    ),
    path(
        "account/holds/<uuid:hold_id>/cancel/",
        views.account_cancel_hold,
        name="account_cancel_hold",
    ),
    path("records/<uuid:instance_id>/", views.record_detail, name="record_detail"),
    path("records/<uuid:instance_id>/hold/", views.record_place_hold, name="record_place_hold"),
    path(
        "records/<uuid:instance_id>/availability/",
        views.record_availability,
        name="record_availability",
    ),
]
