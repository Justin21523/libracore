from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.api import BaseModelViewSet

from .models import Notification, NotificationTemplate
from .serializers import NotificationSerializer, NotificationTemplateSerializer
from .services import generate_notifications, mark_notification_read


class StaffOrOwnNotificationPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if view.basename == "notification-template":
            return request.user.is_staff
        if request.method in permissions.SAFE_METHODS:
            return True
        if view.basename == "notification" and getattr(view, "action", "") == "mark_read":
            return True
        return request.user.is_staff


class NotificationViewSet(BaseModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [StaffOrOwnNotificationPermission]
    search_fields = ["subject", "body", "notification_type"]

    def get_queryset(self):
        queryset = Notification.objects.select_related("recipient_user", "patron").all()
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(recipient_user=self.request.user)

    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        notification = self.get_queryset().get(id=pk)
        mark_notification_read(notification)
        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=["post"])
    def generate(self, request):
        if not request.user.is_staff:
            return Response(
                {"detail": "Staff permission is required."}, status=status.HTTP_403_FORBIDDEN
            )
        counts = generate_notifications(notification_type=request.data.get("type") or None)
        return Response(counts)


class NotificationTemplateViewSet(BaseModelViewSet):
    queryset = NotificationTemplate.objects.all()
    serializer_class = NotificationTemplateSerializer
    permission_classes = [StaffOrOwnNotificationPermission]
    search_fields = ["code", "notification_type", "subject_template"]


def register(router):
    router.register("notifications", NotificationViewSet, basename="notification")
    router.register(
        "notification-templates", NotificationTemplateViewSet, basename="notification-template"
    )
