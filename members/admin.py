from django.contrib import admin
from .models import Member

@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ('id', 'first_name', 'last_name', 'email', 'birth_date', 'active')
    list_filter = ('active',)
    search_fields = ('id', 'first_name', 'last_name', 'email', )
    ordering = ('id',)
    
    # Optional: Add fieldsets for better organization in the edit form
    fieldsets = (
        (None, {
            'fields': ('id', 'first_name', 'last_name', 'email')
        }),
        ('Additional Information', {
            'fields': ('birth_date', 'active')
        }),
        ('System Fields', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        })
    )