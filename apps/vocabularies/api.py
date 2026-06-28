from apps.core.api import BaseModelViewSet, serializer_for
from apps.core.permissions import PublicReadCatalogerWritePermission

from .models import (
    CallNumber,
    ClassificationNumber,
    ClassificationScheme,
    ControlledVocabulary,
    VocabularyTerm,
)


class ControlledVocabularyViewSet(BaseModelViewSet):
    queryset = ControlledVocabulary.objects.all()
    serializer_class = serializer_for(ControlledVocabulary)
    permission_classes = [PublicReadCatalogerWritePermission]
    search_fields = ["code", "name", "source_uri"]


class VocabularyTermViewSet(BaseModelViewSet):
    queryset = VocabularyTerm.objects.select_related("vocabulary", "broader").all()
    serializer_class = serializer_for(VocabularyTerm)
    permission_classes = [PublicReadCatalogerWritePermission]
    search_fields = ["code", "label", "external_uri", "scope_note"]


class ClassificationSchemeViewSet(BaseModelViewSet):
    queryset = ClassificationScheme.objects.all()
    serializer_class = serializer_for(ClassificationScheme)
    permission_classes = [PublicReadCatalogerWritePermission]
    search_fields = ["code", "name", "edition"]


class ClassificationNumberViewSet(BaseModelViewSet):
    queryset = ClassificationNumber.objects.select_related("scheme", "parent").all()
    serializer_class = serializer_for(ClassificationNumber)
    permission_classes = [PublicReadCatalogerWritePermission]
    search_fields = ["number", "caption", "normalized"]


class CallNumberViewSet(BaseModelViewSet):
    queryset = CallNumber.objects.select_related("classification").all()
    serializer_class = serializer_for(CallNumber)
    permission_classes = [PublicReadCatalogerWritePermission]
    search_fields = ["raw", "normalized_sort_key"]


def register(router):
    router.register("vocabularies", ControlledVocabularyViewSet, basename="vocabulary")
    router.register("vocabulary-terms", VocabularyTermViewSet, basename="vocabulary-term")
    router.register(
        "classification-schemes", ClassificationSchemeViewSet, basename="classification-scheme"
    )
    router.register(
        "classification-numbers", ClassificationNumberViewSet, basename="classification-number"
    )
    router.register("call-numbers", CallNumberViewSet, basename="call-number")
