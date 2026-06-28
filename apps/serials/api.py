from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.core.api import BaseModelViewSet

from .models import (
    BoundVolume,
    ClaimEvent,
    Issue,
    IssuePredictionPattern,
    SerialCheckInEvent,
    SerialTitle,
    Subscription,
)
from .serializers import (
    BindIssuesSerializer,
    BoundVolumeSerializer,
    ClaimEventSerializer,
    ClaimIssueSerializer,
    GenerateIssuesSerializer,
    IssuePredictionPatternSerializer,
    IssueSerializer,
    SerialCheckInEventSerializer,
    SerialTitleSerializer,
    SubscriptionSerializer,
)
from .services import (
    ActorContext,
    SerialError,
    bind_issues,
    check_in_issue,
    claim_issue,
    generate_expected_issues,
    mark_issue_missing,
)


def _require_staff(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        raise PermissionDenied("Staff permission is required.")


def _actor_context(request) -> ActorContext:
    return ActorContext(
        actor=request.user,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


def _error_response(exc: SerialError):
    return Response({"code": exc.code, "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class SerialTitleViewSet(BaseModelViewSet):
    queryset = SerialTitle.objects.select_related("instance").all()
    serializer_class = SerialTitleSerializer
    search_fields = ["title", "issn", "frequency"]


class SubscriptionViewSet(BaseModelViewSet):
    queryset = Subscription.objects.select_related(
        "serial_title", "vendor", "branch", "location"
    ).all()
    serializer_class = SubscriptionSerializer
    search_fields = ["serial_title__title", "vendor__name", "notes"]

    @action(detail=True, methods=["post"], url_path="generate-issues")
    def generate_issues(self, request, pk=None):
        _require_staff(request)
        serializer = GenerateIssuesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            issues = generate_expected_issues(
                subscription_id=pk,
                count=serializer.validated_data["count"],
                actor_context=_actor_context(request),
            )
        except SerialError as exc:
            return _error_response(exc)
        return Response(IssueSerializer(issues, many=True).data, status=status.HTTP_201_CREATED)


class IssuePredictionPatternViewSet(BaseModelViewSet):
    queryset = IssuePredictionPattern.objects.select_related("subscription").all()
    serializer_class = IssuePredictionPatternSerializer


class IssueViewSet(BaseModelViewSet):
    queryset = Issue.objects.select_related("serial_title", "holding").all()
    serializer_class = IssueSerializer
    search_fields = ["serial_title__title", "enumeration", "chronology"]

    @action(detail=True, methods=["post"], url_path="check-in")
    def check_in(self, request, pk=None):
        _require_staff(request)
        try:
            issue = check_in_issue(issue_id=pk, actor_context=_actor_context(request))
        except SerialError as exc:
            return _error_response(exc)
        return Response(self.get_serializer(issue).data)

    @action(detail=True, methods=["post"], url_path="mark-missing")
    def mark_missing(self, request, pk=None):
        _require_staff(request)
        issue = mark_issue_missing(issue_id=pk, actor_context=_actor_context(request))
        return Response(self.get_serializer(issue).data)

    @action(detail=True, methods=["post"])
    def claim(self, request, pk=None):
        _require_staff(request)
        serializer = ClaimIssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = claim_issue(
            issue_id=pk,
            note=serializer.validated_data.get("note", ""),
            actor_context=_actor_context(request),
        )
        return Response(ClaimEventSerializer(event).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def bind(self, request):
        _require_staff(request)
        serializer = BindIssuesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            bound = bind_issues(**serializer.validated_data, actor_context=_actor_context(request))
        except SerialError as exc:
            return _error_response(exc)
        return Response(BoundVolumeSerializer(bound).data, status=status.HTTP_201_CREATED)


class SerialCheckInEventViewSet(BaseModelViewSet):
    queryset = SerialCheckInEvent.objects.select_related("issue", "checked_in_by", "item").all()
    serializer_class = SerialCheckInEventSerializer


class ClaimEventViewSet(BaseModelViewSet):
    queryset = ClaimEvent.objects.select_related("issue", "claimed_by").all()
    serializer_class = ClaimEventSerializer


class BoundVolumeViewSet(BaseModelViewSet):
    queryset = BoundVolume.objects.select_related("serial_title", "holding", "item").all()
    serializer_class = BoundVolumeSerializer


def register(router):
    router.register("serial-titles", SerialTitleViewSet, basename="serial-title")
    router.register("subscriptions", SubscriptionViewSet, basename="subscription")
    router.register(
        "issue-prediction-patterns",
        IssuePredictionPatternViewSet,
        basename="issue-prediction-pattern",
    )
    router.register("issues", IssueViewSet, basename="issue")
    router.register(
        "serial-checkin-events", SerialCheckInEventViewSet, basename="serial-checkin-event"
    )
    router.register("claim-events", ClaimEventViewSet, basename="claim-event")
    router.register("bound-volumes", BoundVolumeViewSet, basename="bound-volume")
