from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from loguru import logger
from operations.models import Aircraft, Flight
from operations.utils import verify_icao_location
from invoicing.models import Account
from datetime import datetime, timedelta
from django.utils import timezone
from decimal import Decimal
import csv
import glob
from config import Config

class Command(BaseCommand):
    help = 'Import flight records from CSV'

    def add_arguments(self, parser):
        parser.add_argument('path', type=str, help='path of the .csv file(s), supports wildcards')
        parser.add_argument(
            '--force',
            action='store_true',
            help='Continue import even if there are warnings or duplicates'
        )
        parser.add_argument(
            '--allow-foreign-airports',
            action='store_true',
            help='Allow non-Finnish ICAO codes (default: only allow EF** and maasto)'
        )

    def parse_time(self, time_str, date_str):
        """Helper function to parse time with different formats"""
        try:
            naive_datetime = datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
        except ValueError:
            # Try with period instead of colon
            naive_datetime = datetime.strptime(
                f"{date_str} {time_str.replace('.',':')}", 
                '%Y-%m-%d %H:%M'
            )
        
        return timezone.make_aware(naive_datetime)

    def process_file(self, filename, options):
        successes = 0
        failures = 0
        duplicates = 0

        required_columns = {
            'Selite', 'Tapahtumapäivä', 'Maksajan viitenumero',
            'Lähtöaika', 'Laskeutumisaika', 'Lentoaika_desimaalinen'
        }

        with open(filename, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            # Verify required columns
            missing_columns = required_columns - set(reader.fieldnames)
            if missing_columns:
                raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

            for row in reader:
                try:
                    # Extract registration number from Selite
                    selite_reg = row['Selite'].split()[0].upper()

                    if selite_reg in Config.NO_INVOICING_AIRCRAFT:
                        logger.warning(f"Skipping flight for aircraft {selite_reg} (no-invoicing)")
                        continue

                    # Find aircraft
                    try:
                        aircraft = Aircraft.objects.get(registration__contains=selite_reg)
                    except Aircraft.DoesNotExist:
                        raise ValueError(f"Aircraft {selite_reg} not found in database")

                    # Find account by reference number
                    reference_id = row['Maksajan viitenumero']
                    account = None
                    if reference_id not in Config.NO_INVOICING_REFERENCE_IDS:
                        try:
                            account = Account.objects.get(id=reference_id)
                        except Account.DoesNotExist:
                            raise ValueError(
                                f"Account with missing ID {reference_id}:\n",
                                f"{row}"
                            )


                    # Construct notes
                    notes_parts = []
                    if row.get('Opettaja/Päällikkö'):
                        notes_parts.append(f"Pilot: {row['Opettaja/Päällikkö']}")
                    if row.get('Oppilas/Matkustaja'):
                        notes_parts.append(f"Passenger: {row['Oppilas/Matkustaja']}")
                    if row.get('Tarkoitus'):
                        notes_parts.append(f"Purpose: {row['Tarkoitus']}")
                    if row.get('Laskutuslisä syy'):
                        notes_parts.append(f"Billing note: {row['Laskutuslisä syy']}")

                    # Parse times
                    date = datetime.strptime(row['Tapahtumapäivä'], '%Y-%m-%d')
                    date = timezone.make_aware(date)

                    takeoff_time=self.parse_time(
                        row['Lähtöaika'], 
                        row['Tapahtumapäivä']
                    )

                    landing_time=self.parse_time(
                        row['Laskeutumisaika'], 
                        row['Tapahtumapäivä']
                    )

                    # Sanity check the times
                    if landing_time < takeoff_time:
                        raise ValueError(
                            f"Landing time before takeoff time:\n"
                            f"{row}\n"
                            f"  Takeoff: {takeoff_time}\n"
                            f"  Landing: {landing_time}"
                        )
                    
                    if landing_time - takeoff_time < timedelta(minutes=1):
                        # This might not be wrong, but it's suspicious
                        logger.warning(
                            f"Flight duration less than 1 minute:\n"
                            f"{row}\n"
                            f"  Duration: {landing_time - takeoff_time}"
                        )
                    
                    # If the flight is in the future?
                    if date > timezone.now():
                        raise ValueError(
                            f"Flight date in the future:\n"
                            f"{row}\n"
                            f"  Flight date: {date}"
                        )

                    # Check for required locations when not using force
                    takeoff_location = row.get('Lähtöpaikka')
                    landing_location = row.get('Laskeutumispaikka')
                    
                    # Verify locations
                    if not takeoff_location or not landing_location:
                        if not options['force']:
                            raise ValueError(f"Missing location information in row:\n{row}")
                        else:
                            logger.warning(f"Missing location information in row:\n{row}")
                    else:
                        # Verify ICAO codes
                        if not verify_icao_location(takeoff_location, Config.ENFORCED_ICAO_PREFIX if not (options['allow_foreign_airports'] or options['force']) else None):
                            msg = f"Invalid takeoff location format '{takeoff_location}' in row:\n{row}"
                            if not options['force']:
                                raise ValueError(msg)
                            else:
                                logger.warning(msg)
                        
                        if not verify_icao_location(landing_location, Config.ENFORCED_ICAO_PREFIX if not (options['allow_foreign_airports'] or options['force']) else None):
                            msg = f"Invalid landing location format '{landing_location}' in row:\n{row}"
                            if not options['force']:
                                raise ValueError(msg)
                            else:
                                logger.warning(msg)

                    # Create flight object (but don't save yet)
                    flight = Flight(
                        date=date,  # Make date aware too
                        takeoff_time=takeoff_time,
                        landing_time=landing_time,
                        reference_id=reference_id,
                        aircraft=aircraft,
                        account=account,
                        duration=Decimal(row['Lentoaika_desimaalinen']),
                        notes='\n'.join(notes_parts) if notes_parts else None,
                        purpose=row.get('Tarkoitus'),
                        takeoff_location=row.get('Lähtöpaikka'),
                        landing_location=row.get('Laskeutumispaikka')
                    )

                    existing = Flight.objects.filter(
                        aircraft=flight.aircraft,
                        date__date=flight.date.date(),
                    ).filter(
                        Q(takeoff_time=flight.takeoff_time) | 
                        Q(landing_time=flight.landing_time)
                    ).first()

                    if existing:
                        logger.debug(f"Duplicate flight detected: {flight}")
                        duplicates += 1
                        continue

                    flight.save()
                    successes += 1

                except Exception as e:
                    logger.error(f"Error in row {reader.line_num}: {str(e)}")
                    failures += 1

        return successes, failures, duplicates

    @transaction.atomic
    def handle(self, *args, **options):
        path_pattern = options['path']

        logger.debug(f"Looking for files matching: {path_pattern}")
        
        files = glob.glob(path_pattern)
        if not files:
            raise ValueError(f"No files found matching pattern: {path_pattern}")
        
        logger.info(f"Found {len(files)} files to process")
        
        total_successes = 0
        total_failures = 0
        total_duplicates = 0

        # Process each file
        for filename in files:
            logger.info(f"Processing file: {filename}")
            successes, failures, duplicates = self.process_file(filename, options)
            total_successes += successes
            total_failures += failures
            total_duplicates += duplicates

            logger.info(f"In file {filename}: Imported: {successes}, Failed: {failures}, Duplicates: {duplicates}")
        
        if total_failures or total_duplicates:
            logger.warning(f"Flight import completed. Imported: {total_successes}, Failed: {total_failures}, Duplicates: {total_successes}")
        else:
            logger.info(f"Flight import completed. Imported: {total_successes}, Failed: {total_failures}, Duplicates: {total_successes}")
        
        if total_failures:
            logger.warning(f"Encountered {total_failures} failures during processing")
            if not options['force']:
                transaction.set_rollback(True)
                logger.error("Rolling back transaction due to errors")
