from django.contrib import admin
from django.utils.html import format_html
from .models import Aircraft, Flight

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
        'airfields',  # New field
        'duration_display',
        'purpose'
    )
    list_filter = ('aircraft', 'purpose', 'date')
    search_fields = ('reference_id', 'notes')
    date_hierarchy = 'date'

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
