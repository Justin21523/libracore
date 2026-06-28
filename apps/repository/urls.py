from django.urls import path

from . import views

app_name = "repository"

urlpatterns = [
    path("repository/", views.repository_list, name="list"),
    path("repository/<uuid:object_id>/", views.repository_detail, name="detail"),
    path("repository/files/<uuid:asset_id>/download/", views.file_download, name="file_download"),
]
