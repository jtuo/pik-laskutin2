from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal

class Aircraft(models.Model):
    registration = models.CharField(max_length=10, unique=True)
    competition_id = models.CharField(max_length=4, blank=True, null=True)
    name = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        db_table = 'aircraft'
        verbose_name = 'aircraft'
        verbose_name_plural = 'aircraft'

    def clean(self):
        if not self.registration:
            raise ValidationError("Registration cannot be empty")
        self.registration = self.registration.upper()

    def __str__(self):
        return f"<{self.registration}>"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class BaseEvent(models.Model):
    account = models.ForeignKey(
        'invoicing.Account',
        on_delete=models.CASCADE,
        db_column='account_id',
        null=True,
        related_name='events'
    )
    
    reference_id = models.CharField(max_length=20, db_index=True, null=True)
    date = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'events'

class Flight(BaseEvent):
    takeoff_time = models.DateTimeField()
    landing_time = models.DateTimeField()
    aircraft = models.ForeignKey(
        Aircraft,
        on_delete=models.CASCADE,
        related_name='flights'
    )
    duration = models.DecimalField(max_digits=5, decimal_places=2)
    purpose = models.CharField(max_length=10, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'flights'

        # Enforces unique flights
        # No flight can exist with the same date, aircraft, takeoff and landing times
        constraints = [
            models.UniqueConstraint(
                fields=['aircraft', 'takeoff_time', 'landing_time'],
                name='flight_time_slot_per_aircraft_unique'
            )
        ]

    def __str__(self):
        return f"<Flight {self.reference_id} on {self.date}>"