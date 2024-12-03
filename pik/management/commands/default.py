from django.core.management.base import BaseCommand
from operations.models import Aircraft
from django.db import transaction

class Command(BaseCommand):
    help = 'Adds default aircraft to the database'

    def handle(self, *args, **options):
        aircraft_data = [
            Aircraft(registration="OH-952", name="DG"),
            Aircraft(registration="OH-733", name="Acro", competition_id="FQ"),
            Aircraft(registration="OH-787", name="LS-4a", competition_id="FM"),
            Aircraft(registration="OH-1035", name="LS-4", competition_id="FI"),
            Aircraft(registration="OH-883", name="LS-8", competition_id="FY"),
            Aircraft(registration="OH-650", name="Club Astir", competition_id="FK"),
            Aircraft(registration="OH-1037", name="Tuulia"),
            Aircraft(registration="OH-TOW", name="Suhinu"),
        ]

        try:
            with transaction.atomic():
                for aircraft in aircraft_data:
                    aircraft.save()
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Added aircraft {aircraft.registration}'
                        )
                    )
        
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error: {str(e)}')
            )
            return
