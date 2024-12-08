from django.contrib import admin
from django.contrib import messages
from django.utils.html import format_html
from .models import Account, AccountEntry, AccountEntryTag, Invoice

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('id', 'member', 'name', 'created_at', 'show_balance_button', 'show_overdue_button', 'show_last_payment')
    search_fields = ['id', 'name']
    date_hierarchy = 'created_at'
    actions = ['show_balance', 'show_days_overdue']

    def show_balance_button(self, obj):
        balance = obj.balance
        return format_html(
            '<span style="color: {color};">{amount} €</span>',
            color='lime' if balance <= 0 else 'red',
            amount="{:.2f}".format(balance)
        )
    show_balance_button.short_description = "Balance"

    def show_overdue_button(self, obj):
        days = obj.days_overdue
        if days is None:
            return format_html(
                '<span style="color: lime;">Not overdue</span>'
            )
        
        if days > 400:
            color = 'red'
        elif days > 120:
            color = 'orange'
        else:
            color = 'inherit'
            
        return format_html(
            '<span style="color: {color};">{days} days</span>',
            color=color,
            days=days
        )
    show_overdue_button.short_description = "Overdue"

    def show_last_payment(self, obj):
        days = obj.days_since_last_payment
        if days is None:
            return format_html(
                '<span style="color: gray;">No payments</span>'
            )
        
        # Only show red if both conditions are met:
        # 1. Last payment was over 400 days ago
        # 2. Account is currently overdue
        show_red = days > 400 and obj.days_overdue is not None
        
        return format_html(
            '<span style="color: {color};">{days} days ago</span>',
            color='red' if show_red else 'inherit',
            days=days
        )
    show_last_payment.short_description = "Last Payment"

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
    list_display = ('date_display', 'account', 'description', 'amount', 'has_invoices', 'additive')
    list_filter = ('additive', 'created_at')
    search_fields = ('description', 'account__name')
    date_hierarchy = 'date'
    readonly_fields = ('created_at',)
    ordering = ('-date',)

    def date_display(self, obj):
        """Format date in Finnish style (dd.mm.yyyy)"""
        return obj.date.strftime('%d.%m.%Y')
    
    date_display.short_description = 'Date'
    date_display.admin_order_field = 'date'

    def has_invoices(self, obj):
        """Indicate if there are invoices associated with the account entry"""
        return obj.invoices.exists()
    
    has_invoices.short_description = 'Has Invoices'
    has_invoices.boolean = True  # Display as a boolean icon

@admin.register(AccountEntryTag)
class AccountEntryTagAdmin(admin.ModelAdmin):
    list_display = ('value', 'entry')
    search_fields = ('value', 'entry__description')
    list_filter = ('value',)
    raw_id_fields = ('entry',)

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
