from apps.core.api import BaseModelViewSet, serializer_for

from .models import Branch, Holding, Item, Location


class BranchViewSet(BaseModelViewSet):
    queryset = Branch.objects.all()
    serializer_class = serializer_for(Branch)
    search_fields = ["code", "name", "address"]


class LocationViewSet(BaseModelViewSet):
    queryset = Location.objects.select_related("branch").all()
    serializer_class = serializer_for(Location)
    search_fields = ["code", "name", "shelving_area"]


class HoldingViewSet(BaseModelViewSet):
    queryset = Holding.objects.select_related("instance", "branch", "location", "call_number").all()
    serializer_class = serializer_for(Holding)
    search_fields = ["public_note", "textual_holdings", "instance__title_statement"]


class ItemViewSet(BaseModelViewSet):
    queryset = Item.objects.select_related("holding", "holding__instance").all()
    serializer_class = serializer_for(Item)
    search_fields = ["barcode", "copy_number", "inventory_number", "holding__instance__title_statement"]
    ordering_fields = ["barcode", "status", "acquired_at", "created_at"]


def register(router):
    router.register("branches", BranchViewSet, basename="branch")
    router.register("locations", LocationViewSet, basename="location")
    router.register("holdings", HoldingViewSet, basename="holding")
    router.register("items", ItemViewSet, basename="item")

