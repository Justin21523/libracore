from django.urls import path

from . import views

app_name = "authorities"

urlpatterns = [
    path("authorities/", views.authority_browse, name="browse"),
    path("authorities/<uuid:authority_id>/", views.authority_detail, name="detail"),
    path("subjects/", views.subject_browse, name="subjects"),
]

