from datetime import datetime
from decimal import Decimal, InvalidOperation as decimal_InvalidOperation
import csv
from loguru import logger
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from zoneinfo import ZoneInfo
from invoicing.models import Account, AccountEntry

class Command(BaseCommand):
    help = 'Import balance records from a CSV file'

    def add_arguments(self, parser):
        parser.add_argument('filename', type=str, help='Path to the CSV file')

    def handle(self, *args, **options):
        filename = options['filename']
        count = 0
        failed = 0

        logger.debug(f"Importing balance records from {filename}")

        try:
            with open(filename, 'r', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)  # Using reader not DictReader since columns are unnamed
                
                with transaction.atomic():
                    for row in reader:
                        # Skip empty lines
                        if not row or not any(row):
                            continue
                            
                        try:
                            if len(row) != 4:
                                raise ValueError(f"Expected 4 columns, got {len(row)}")
                            
                            # Skip if any required field is empty
                            if not all(row):
                                logger.warning(f"Skipping row {reader.line_num}: Empty required field")
                                failed += 1
                                continue

                            # Parse date
                            try:
                                naive_datetime = datetime.strptime(row[0], '%Y-%m-%d')
                                date = timezone.make_aware(
                                    naive_datetime, 
                                    timezone=ZoneInfo('Europe/Helsinki')
                                )
                            except ValueError:
                                raise ValueError(f"Invalid date format: {row[0]}. Use YYYY-MM-DD")

                            # Get account
                            try:
                                account = Account.objects.get(id=row[1])
                            except Account.DoesNotExist:
                                logger.warning(f"Account with reference ID {row[1]} not found")
                                failed += 1
                                continue

                            # Parse balance amount
                            try:
                                balance = Decimal(row[3])
                            except (decimal_InvalidOperation, ValueError) as e:
                                logger.error(f"Error parsing balance '{row[3]}': {str(e)}")
                                failed += 1
                                continue

                            # Create new AccountEntry with additive set to False
                            entry = AccountEntry.objects.create(
                                account=account,
                                date=date,
                                amount=balance,  # Use balance directly as amount
                                description=row[2],
                                additive=False  # CRITICAL
                            )
                            count += 1
                            logger.debug(f"Added balance entry: {entry.date} | {entry.amount} | {entry.description}")

                        except Exception as e:
                            error_msg = f"Error in row {reader.line_num}: {str(e)}"
                            logger.exception(error_msg)
                            raise  # Re-raise to trigger rollback

        except FileNotFoundError:
            logger.exception(f"File not found: {filename}")
            return

        logger.info(f"Balance import completed: {count} entries imported, {failed} failed")