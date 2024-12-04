from django.contrib import admin
from .models import Account, AccountEntry, Invoice

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('id', 'member', 'name', 'created_at')
    search_fields = ('id', 'name', 'member__name')
    date_hierarchy = 'created_at'

    def get_queryset(self, request):
        """Only show accounts with members by default"""
        qs = super().get_queryset(request)
        has_member = request.GET.get('has_member')
        if has_member == 'no':
            return qs.filter(member__isnull=True)
        elif has_member == 'all':
            return qs
        # Default to showing only accounts with members
        return qs.exclude(member__isnull=True)

    def get_list_filter(self, request):
        class HasMemberFilter(admin.SimpleListFilter):
            title = 'has member'
            parameter_name = 'has_member'

            def lookups(self, request, model_admin):
                return (
                    ('yes', 'Yes'),
                    ('no', 'No'),
                )

            def queryset(self, request, queryset):
                if self.value() == 'yes':
                    return queryset.exclude(member__isnull=True)
                elif self.value() == 'no':
                    return queryset.filter(member__isnull=True)
                return queryset

        return (HasMemberFilter,)

@admin.register(AccountEntry)
class AccountEntryAdmin(admin.ModelAdmin):
    list_display = ('date_display', 'account', 'description', 'amount', 'invoice', 'additive')
    list_filter = ('additive', 'created_at')
    search_fields = ('description', 'account__name')
    date_hierarchy = 'date'
    readonly_fields = ('created_at',)
    ordering = ('-date',)

    def date_display(self, obj):
        """Format date in Finnish style (dd.mm.yyyy)"""
        return obj.date.strftime('%d.%m.%Y')
    
    date_display.short_description = 'Date'
    date_display.admin_order_field = 'date'  # Maintain sorting ability

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('number', 'account', 'created_at', 'due_date', 'status', 'total_amount')
    list_filter = ('status', 'created_at')
    search_fields = ('number', 'account__name', 'notes')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)

    def total_amount(self, obj):
        return obj.total_amount
    total_amount.short_description = 'Total Amount'
