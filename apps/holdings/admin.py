from django.contrib import admin

from .models import Branch, Holding, Item, Location


admin.site.register(Branch)
admin.site.register(Location)
admin.site.register(Holding)
admin.site.register(Item)

