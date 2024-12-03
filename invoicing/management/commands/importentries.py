from datetime import datetime
from decimal import Decimal, InvalidOperation as decimal_InvalidOperation
import csv
from loguru import logger
from django.core.management.base import BaseCommand
from django.db import transaction
from invoicing.models import Account, AccountEntry
from django.utils import timezone

class Command(BaseCommand):
    help = 'Import account entries from a CSV file'

    def add_arguments(self, parser):
        parser.add_argument('filename', type=str, help='Path to the CSV file')

    def handle(self, *args, **options):
        filename = options['filename']
        count = 0
        failed = 0

        self.stdout.write(f"Importing entries from {filename}")

        try:
            with open(filename, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                # Verify required columns
                required_columns = {'Tapahtumapäivä', 'Maksajan viitenumero', 'Selite', 'Summa', 'Tili'}
                missing_columns = required_columns - set(reader.fieldnames)
                if missing_columns:
                    raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

                # Use transaction.atomic to ensure database consistency
                with transaction.atomic():
                    for row in reader:
                        try:
                            # Parse date and make it timezone-aware
                            try:
                                naive_datetime = datetime.strptime(row['Tapahtumapäivä'], '%Y-%m-%d')
                                date = timezone.make_aware(naive_datetime)
                            except ValueError:
                                raise ValueError(
                                    f"Invalid date format: {row['Tapahtumapäivä']}. Use YYYY-MM-DD"
                                )

                            # Find account by reference number
                            try:
                                account = Account.objects.get(id=row['Maksajan viitenumero'])
                            except Account.DoesNotExist:
                                logger.warning(
                                    f"Account with reference ID {row['Maksajan viitenumero']} not found"
                                )
                                failed += 1
                                continue

                            # Parse amount
                            try:
                                amount = Decimal(row['Summa'].replace(',', '.'))
                            except (ValueError, decimal_InvalidOperation):
                                raise ValueError(f"Invalid amount format: {row['Summa']}")

                            # Create new AccountEntry
                            AccountEntry.objects.create(
                                account=account,
                                date=date,
                                amount=amount,
                                description=row['Selite'],
                                ledger_account_id=row['Tili']
                            )
                            count += 1

                        except Exception as e:
                            error_msg = f"Error in row {reader.line_num}: {str(e)}"
                            logger.error(error_msg)
                            self.stdout.write(self.style.ERROR(error_msg))
                            failed += 1
                            continue

        except FileNotFoundError:
            logger.exception(f"File not found: {filename}")
            return

        logger.info(
            f"Import completed. Imported: {count}, Failed: {failed}"
        )