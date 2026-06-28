from apps.core.api import BaseModelViewSet, serializer_for
from apps.core.permissions import PublicReadCatalogerWritePermission

from .models import (
    BibliographicRecord,
    Expression,
    Instance,
    InstanceContributor,
    Work,
    WorkAuthorityLink,
)


class WorkViewSet(BaseModelViewSet):
    queryset = Work.objects.all()
    serializer_class = serializer_for(Work)
    permission_classes = [PublicReadCatalogerWritePermission]
    search_fields = ["primary_title", "original_title", "summary"]
    ordering_fields = ["primary_title", "date", "created_at"]


class ExpressionViewSet(BaseModelViewSet):
    queryset = Expression.objects.select_related("work").all()
    serializer_class = serializer_for(Expression)
    permission_classes = [PublicReadCatalogerWritePermission]
    search_fields = ["title", "language", "content_type"]


class InstanceViewSet(BaseModelViewSet):
    queryset = Instance.objects.select_related("work", "expression").all()
    serializer_class = serializer_for(Instance)
    permission_classes = [PublicReadCatalogerWritePermission]
    search_fields = ["title_statement", "responsibility_statement", "publisher", "publication_date"]
    ordering_fields = ["title_statement", "publication_date", "created_at"]


class BibliographicRecordViewSet(BaseModelViewSet):
    queryset = BibliographicRecord.objects.select_related("work", "instance").all()
    serializer_class = serializer_for(BibliographicRecord)
    permission_classes = [PublicReadCatalogerWritePermission]
    search_fields = ["control_number", "source", "instance__title_statement", "work__primary_title"]
    ordering_fields = ["status", "source", "created_at", "updated_at"]


class WorkAuthorityLinkViewSet(BaseModelViewSet):
    queryset = WorkAuthorityLink.objects.select_related("work", "authority").all()
    serializer_class = serializer_for(WorkAuthorityLink)
    permission_classes = [PublicReadCatalogerWritePermission]


class InstanceContributorViewSet(BaseModelViewSet):
    queryset = InstanceContributor.objects.select_related("instance", "authority").all()
    serializer_class = serializer_for(InstanceContributor)
    permission_classes = [PublicReadCatalogerWritePermission]


def register(router):
    router.register("works", WorkViewSet, basename="work")
    router.register("expressions", ExpressionViewSet, basename="expression")
    router.register("instances", InstanceViewSet, basename="instance")
    router.register(
        "bibliographic-records", BibliographicRecordViewSet, basename="bibliographic-record"
    )
    router.register(
        "work-authority-links", WorkAuthorityLinkViewSet, basename="work-authority-link"
    )
    router.register(
        "instance-contributors", InstanceContributorViewSet, basename="instance-contributor"
    )
