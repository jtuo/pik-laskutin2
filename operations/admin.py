from django.contrib import admin
from django.utils.html import format_html
from .models import Aircraft, Flight
from invoicing.logic.engine import create_default_engine

@admin.register(Aircraft)
class AircraftAdmin(admin.ModelAdmin):
    list_display = ('registration', 'competition_id', 'name')
    search_fields = ('registration', 'name')

@admin.register(Flight)
class FlightAdmin(admin.ModelAdmin):
    list_display = (
        'reference_id',
        'date_display',  # Custom method for Finnish date format
        'aircraft',
        'flight_times',
        'airfields',
        'duration_display',
        'purpose',
        'captain',
        'refund_status'  # Added refund status indicator
    )
    list_filter = ('aircraft', 'purpose', 'date')
    search_fields = ('reference_id', 'notes', 'captain', 'passengers')
    date_hierarchy = 'date'
    actions = ['refund_events', 'remove_refunds']

    def refund_events(self, request, queryset):
        """Create refund entries for selected events"""
        engine = create_default_engine()
        refunded = 0
        for event in queryset:
            if engine.refund_event(event):
                refunded += 1
        self.message_user(request, f'Successfully refunded {refunded} events.')
    refund_events.short_description = 'Create refund entries for selected events'

    def remove_refunds(self, request, queryset):
        """Remove refund entries from selected events"""
        removed = 0
        for event in queryset:
            if event.has_been_refunded:
                # Delete the refund entry
                event.refund_entry.delete()
                event.refund_entry = None
                event.save()
                removed += 1
        self.message_user(request, f'Successfully removed refunds from {removed} events.')
    remove_refunds.short_description = 'Remove refund entries from selected events'

    def refund_status(self, obj):
        """Display refund status with color coding"""
        if obj.has_been_refunded:
            return format_html(
                '<span style="color: #c41e3a;">Refunded</span>'
            )
        return format_html(
            '<span style="color: #2e8b57;">Active</span>'
        )
    refund_status.short_description = 'Status'

    def flight_times(self, obj):
        """Format takeoff and landing times nicely"""
        return format_html(
            '{} → {}',
            obj.takeoff_time.strftime('%H:%M'),
            obj.landing_time.strftime('%H:%M')
        )
    flight_times.short_description = 'Flight Times'

    def date_display(self, obj):
        """Format date in Finnish style (dd.mm.yyyy)"""
        return obj.date.strftime('%d.%m.%Y')
    date_display.short_description = 'Date'
    date_display.admin_order_field = 'date'  # Maintain sorting ability

    def duration_display(self, obj):
        """Format duration as hours and minutes (when duration is in minutes)"""
        hours = int(float(obj.duration) // 60)  # Integer division by 60 to get hours
        minutes = int(float(obj.duration) % 60)  # Remainder to get minutes
        return f'{hours}:{minutes:02d}'
    duration_display.short_description = 'Duration'
    duration_display.admin_order_field = 'duration'

    def airfields(self, obj):
        """Format takeoff and landing locations nicely"""
        if obj.takeoff_location or obj.landing_location:
            return format_html(
                '{} → {}',
                obj.takeoff_location or '?',
                obj.landing_location or '?'
            )
        return '-'
    airfields.short_description = 'Locations'

    ordering = ('-date', 'takeoff_time')
