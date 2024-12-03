from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from loguru import logger
from operations.models import Aircraft, Flight
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
            '--dry-run',
            action='store_true',
            help='Validate the import without saving'
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

    def process_file(self, filename):
        flights_to_add = []
        failed_rows = []

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
                        logger.warning(
                            f"Skipping flight for aircraft {selite_reg} (no-invoicing)"
                        )
                        continue

                    # Find aircraft
                    try:
                        aircraft = Aircraft.objects.get(
                            registration__contains=selite_reg
                        )
                    except Aircraft.DoesNotExist:
                        raise ValueError(f"Aircraft {selite_reg} not found in database")

                    # Find account by reference number
                    reference_id = row['Maksajan viitenumero']
                    account = None
                    if reference_id not in Config.NO_INVOICING_REFERENCE_IDS:
                        try:
                            account = Account.objects.get(id=reference_id)
                        except Account.DoesNotExist:
                            logger.warning(
                                f"Account with reference ID {reference_id} not found in row {reader.line_num}:\n"
                                f"{row}"
                            )
                            continue

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

                    departure_time=self.parse_time(
                        row['Lähtöaika'], 
                        row['Tapahtumapäivä']
                    )

                    landing_time=self.parse_time(
                        row['Laskeutumisaika'], 
                        row['Tapahtumapäivä']
                    )

                    # Sanity check the times
                    if landing_time < departure_time:
                        #raise ValueError("Landing time cannot be before departure time")
                        logger.warning(
                            f"Landing time before departure time in row {reader.line_num}:\n"
                            f"{row}\n"
                            f"  Departure: {departure_time}\n"
                            f"  Landing: {landing_time}"
                        )
                        continue
                    
                    if landing_time - departure_time < timedelta(minutes=1):
                        #raise ValueError("Flight duration must be at least 1 minute")
                        logger.warning(
                            f"Flight duration less than 1 minute in row {reader.line_num}:\n"
                            f"{row}\n"
                            f"  Duration: {landing_time - departure_time}"
                        )
                        continue
                    
                    # If the flight is in the future?
                    if date > timezone.now():
                        #raise ValueError("Flight date cannot be in the future")
                        logger.warning(
                            f"Flight date in the future in row {reader.line_num}:\n"
                            f"{row}\n"
                            f"  Flight date: {date}"
                        )
                        continue

                    # Create flight object (but don't save yet)
                    flight = Flight(
                        date=date,  # Make date aware too
                        departure_time=departure_time,
                        landing_time=landing_time,
                        reference_id=reference_id,
                        aircraft=aircraft,
                        account=account,
                        duration=Decimal(row['Lentoaika_desimaalinen']),
                        notes='\n'.join(notes_parts) if notes_parts else None,
                        purpose=row.get('Tarkoitus')
                    )

                    flights_to_add.append(flight)

                except Exception as e:
                    error_msg = f"Error in row {reader.line_num}: {str(e)}"
                    logger.error(error_msg)
                    failed_rows.append((row, error_msg))

        return flights_to_add, failed_rows

    @transaction.atomic
    def handle(self, *args, **options):
        path_pattern = options['path']
        dry_run = options['dry_run']

        logger.debug(f"Looking for files matching: {path_pattern}")
        
        files = glob.glob(path_pattern)
        if not files:
            raise ValueError(f"No files found matching pattern: {path_pattern}")
        
        logger.info(f"Found {len(files)} files to process")
        
        all_flights = []
        all_failed_rows = []
        duplicate_count = 0

        # Process each file
        for filename in files:
            try:
                logger.info(f"Processing file: {filename}")
                flights, failed_rows = self.process_file(filename)
                
                # Check each flight for duplicates before adding to all_flights
                for flight in flights:
                    # Check for existing flight with same aircraft and date, and matching either time
                    existing = Flight.objects.filter(
                        aircraft=flight.aircraft,
                        date__date=flight.date.date(),
                    ).filter(
                        Q(departure_time=flight.departure_time) | 
                        Q(landing_time=flight.landing_time)
                    ).first()
                    
                    if existing:
                        duplicate_count += 1
                        logger.debug(
                            f"Duplicate flight detected:\n"
                            f"  Aircraft: {flight.aircraft.registration}\n"
                            f"  Date: {flight.date.date()}\n"
                            f"  Times: {flight.departure_time.time()} - {flight.landing_time.time()}\n"
                            f"  Account: {flight.account.id if flight.account else 'None'}\n"
                            f"  Purpose: {flight.purpose or 'None'}\n"
                            f"Matches existing flight:\n"
                            f"  Times: {existing.departure_time.time()} - {existing.landing_time.time()}\n"
                            f"  Account: {existing.account.id if existing.account else 'None'}\n"
                            f"  Purpose: {existing.purpose or 'None'}"
                        )
                    else:
                        all_flights.append(flight)
                
                all_failed_rows.extend(failed_rows)
                logger.info(f"Found {len(flights)} valid flights in {filename}")
            except Exception as e:
                logger.error(f"Error processing file {filename}: {str(e)}")
                raise

        if all_failed_rows:
            logger.warning(f"Failed to import {len(all_failed_rows)} rows")
            for row, error in all_failed_rows:
                logger.debug(f"Failed row: {row}")
                logger.debug(f"Error: {error}")
            raise ValueError(
                f"Failed to import {len(all_failed_rows)} rows. No flights were imported."
            )

        total_count = len(all_flights)
        logger.info(f"Found total of {total_count} valid flights")

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Dry run: would import {total_count} flights from {len(files)} files. '
                    f'Found {duplicate_count} duplicates that would be skipped.'
                )
            )
            return total_count, all_failed_rows

        # Save all flights in one transaction
        for flight in all_flights:
            flight.save()

        logger.info(
            f'Successfully imported {total_count} flights from {len(files)} files. '
            f'Skipped {duplicate_count} duplicate flights.'
        )
