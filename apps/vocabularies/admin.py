from django.contrib import admin

from .models import CallNumber, ClassificationNumber, ClassificationScheme, ControlledVocabulary, VocabularyTerm


admin.site.register(ControlledVocabulary)
admin.site.register(VocabularyTerm)
admin.site.register(ClassificationScheme)
admin.site.register(ClassificationNumber)
admin.site.register(CallNumber)

