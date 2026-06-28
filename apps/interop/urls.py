from django.urls import path

from . import views

app_name = "interop"

urlpatterns = [
    path("oai/", views.oai_endpoint, name="oai"),
    path("sru/", views.sru_endpoint, name="sru"),
]
