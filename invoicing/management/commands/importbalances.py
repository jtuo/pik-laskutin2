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
        parser.add_argument('--force', action='store_true', help='Force import even if some entries fail, does not import duplicates')
        parser.add_argument('--force-duplicates', action='store_true', help='Force import even if some entries are duplicates')

    @transaction.atomic
    def handle(self, *args, **options):
        filename = options['filename']
        count = 0
        failed = 0
        duplicates = 0

        logger.info(f"Importing balance records from {filename}")

        try:
            with open(filename, 'r', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)  # Using reader not DictReader since columns are unnamed
                
                for row in reader:
                    # Skip empty lines
                    if not row or not any(row):
                        continue
                        
                    try:
                        if len(row) != 4:
                            raise ValueError(f"Expected 4 columns, got {len(row)}")
                        
                        # Skip if any required field is empty
                        if not all(row):
                            raise ValueError(f"Skipping row {reader.line_num}: Empty required field")

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
                            if not options['force']:
                                raise ValueError(f"Account with reference ID {row[1]} not found")
                            logger.warning(f"Account with reference ID {row[1]} not found, creating new account!")
                            account = Account.objects.create(id=row[1])

                        # Parse balance amount
                        try:
                            balance = Decimal(row[3])
                        except (decimal_InvalidOperation, ValueError) as e:
                            raise ValueError(f"Error parsing balance '{row[3]}': {str(e)}")
                        
                        # Check for duplicates
                        if AccountEntry.objects.filter(
                            account=account,
                            date=date,
                            amount=balance,
                            description=row[2],
                            additive=False
                        ).exists():
                            duplicates += 1
                            if not options['force_duplicates']:
                                logger.warning(f"Skipping duplicate balance entry: {account} | {date} | {balance} | {row[2]}")
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
                        logger.warning(error_msg)
                        failed += 1

        except FileNotFoundError:
            logger.exception(f"File not found: {filename}")
            return
        
        logger.info(f"Balance import completed: Imported: {count}, Failed: {failed}, Duplicates: {duplicates}")
        
        if failed and not options['force']:
            logger.error(f"Rolling back transaction due to {failed} failed entries")
            transaction.set_rollback(True)