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
        parser.add_argument(
            '--assume-one-landing',
            action='store_true',
            help='If landing count is not specified or cannot be parsed, assume one landing'
        )
        parser.add_argument(
            '--allow-duration-mismatch',
            action='store_true',
            help='Allow duration mismatch between takeoff/landing times and reported duration'
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
    
    def parse_registration(self, registration: str) -> str:
        return registration.upper()

    def process_file(self, filename, options):
        successes = 0
        failures = 0
        duplicates = 0

        required_columns = {
            'Selite', 'Tapahtumapäivä', 'Maksajan viitenumero',
            'Lähtöaika', 'Laskeutumisaika', 'Lentoaika_desimaalinen',
            'Laskuja'
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
                    selite_reg = self.parse_registration(row['Selite'])

                    if selite_reg in Config.NO_INVOICING_AIRCRAFT:
                        logger.warning(f"Skipping flight for aircraft {selite_reg} (no-invoicing)")
                        continue

                    # Use AIRCRAFT_METADATA_MAP to add metadata to the flight
                    # Mainly implemented as a workaround to account for 1037-opeale flights
                    metadata_override = {}
                    if hasattr(Config, 'AIRCRAFT_METADATA_MAP'):
                        for pattern, override in Config.AIRCRAFT_METADATA_MAP.items():
                            if pattern.upper() == selite_reg:
                                metadata_override = override
                                if 'aircraft' in override:
                                    selite_reg = self.parse_registration(override['aircraft'])
                                    metadata_override = {k: v for k, v in override.items() if k != 'aircraft'}
                                else:
                                    metadata_override = override
                                break

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

                    # Extract captain and passengers
                    captain = row.get('Opettaja/Päällikkö')
                    passengers = row.get('Oppilas/Matkustaja')

                    # Construct notes
                    notes_parts = None

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
                        msg = (
                            f"Landing time before takeoff time:\n"
                            f"{row}\n"
                            f"  Takeoff: {takeoff_time}\n"
                            f"  Landing: {landing_time}"
                        )
                        if not options['force']:
                            raise ValueError(msg)
                        else:
                            logger.warning(msg)

                    if landing_time - takeoff_time < timedelta(minutes=1):
                        # This might not be wrong, but it's suspicious
                        logger.warning(
                            f"Flight duration less than 1 minute:\n"
                            f"{row}\n"
                            f"  Duration: {landing_time - takeoff_time}"
                        )

                    # If the flight is in the future?
                    if date > timezone.now():
                        msg = (
                            f"Flight date in the future:\n"
                            f"{row}\n"
                            f"  Flight date: {date}"
                        )
                        if not options['force']:
                            raise ValueError(msg)
                        else:
                            logger.warning(msg)

                    # Does the landing_time and takeoff_time match the duration?
                    duration = Decimal(row['Lentoaika_desimaalinen'])

                    time_difference = landing_time - takeoff_time
                    actual_duration = Decimal(time_difference.total_seconds()) / 60

                    # We can allow the mismatch if the purpose of the flight is HIN (towing)
                    if row['Tarkoitus'] != 'HIN' and actual_duration != duration:
                        msg = (
                            f"Duration mismatch in row:\n"
                            f"{row}\n"
                            f"  Calculated duration (landing - takeoff): {actual_duration} minutes\n"
                            f"  Reported duration: {duration} minutes"
                        )
                        if not options['force'] and not options['allow_duration_mismatch']:
                            raise ValueError(msg)
                        else:
                            logger.warning(msg)

                    # Check for required locations when not using force
                    takeoff_location = row.get('Lähtöpaikka')
                    landing_location = row.get('Laskeutumispaikka')

                    # There must be at least one landing
                    try:
                        landing_count = int(row.get('Laskuja', 0))
                        if landing_count < 1:
                            if options['assume_one_landing']:
                                logger.warning(f"Assuming one landing for row with {landing_count} landings:\n{row}")
                                landing_count = 1
                            else:
                                raise ValueError(
                                    f"Flight with less than one landing:\n"
                                    f"{row}\n"
                                    f"  Landings: {landing_count}"
                                )
                    except ValueError:
                        if options['assume_one_landing'] or options['force']:
                            logger.warning(f"Could not parse landing count, assuming one landing:\n{row}")
                            landing_count = 1
                        else:
                            raise ValueError(f"Error parsing landing count in row:\n{row}")
                    
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
                    
                    # Workaround for Google Sheets weirdness?
                    # Search which row contains has "laskutuslisä" (non case sensitive)
                    for key, value in row.items():
                        if "laskutuslisä" in key.lower():
                            row['Laskutuslisä syy'] = value
                            break

                    # Create flight object (but don't save yet)
                    flight_data = {
                        'date': date,  # Make date aware too
                        'takeoff_time': takeoff_time,
                        'landing_time': landing_time,
                        'reference_id': reference_id,
                        'aircraft': aircraft,
                        'account': account,
                        'duration': duration,
                        'notes': '\n'.join(notes_parts) if notes_parts else None,
                        'captain': captain,
                        'passengers': passengers,
                        'surcharge_reason': row.get('Laskutuslisä syy'),
                        'purpose': row.get('Tarkoitus'),
                        'takeoff_location': row.get('Lähtöpaikka'),
                        'landing_location': row.get('Laskeutumispaikka'),
                        'landing_count': landing_count,
                    }

                    # Apply any metadata overrides
                    flight_data.update(metadata_override)
                    
                    flight = Flight(**flight_data)

                    existing = Flight.objects.filter(
                        aircraft=flight.aircraft,
                        date=flight.date,
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
            logger.warning(f"Flight import completed. Imported: {total_successes}, Failed: {total_failures}, Duplicates: {total_duplicates}")
        else:
            logger.info(f"Flight import completed. Imported: {total_successes}, Failed: {total_failures}, Duplicates: {total_duplicates}")
        
        if total_failures:
            logger.warning(f"Encountered {total_failures} failures during processing")
            if not options['force']:
                transaction.set_rollback(True)
                logger.error("Rolling back transaction due to errors")
