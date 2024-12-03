from datetime import datetime
from decimal import Decimal
from loguru import logger
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from zoneinfo import ZoneInfo
from invoicing.models import Account, AccountEntry
from invoicing.io.nda import NDAFileParser
from config import Config
import glob
import os

class Command(BaseCommand):
    help = 'Import bank transactions from .nda files'

    def add_arguments(self, parser):
        parser.add_argument('filename_pattern', type=str, help='Path/pattern for .nda files (wildcards allowed)')
        parser.add_argument('--force', action='store_true', help='Force import even if some entries fail')

    @transaction.atomic
    def handle(self, *args, **options):
        pattern = options['filename_pattern']
        total_count = 0
        total_failed = 0
        total_duplicates = 0

        # Get list of files matching the pattern
        files = glob.glob(pattern)
        if not files:
            logger.error(f"No files found matching pattern: {pattern}")
            return

        logger.info(f"Found {len(files)} files to process")

        account_numbers = Config.NDA_ACCOUNTS
        if not account_numbers:
            logger.error("There are no bank accounts provided for NDA import")
            return
        else:
            logger.debug(f"Using provided bank accounts: {account_numbers}")

        nda_parser = NDAFileParser()

        # Process each file
        for filename in files:
            logger.debug(f"Starting NDA transaction import from {filename}")
            count = 0
            failed = 0
            duplicates = 0

            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    # Use the new parser to get transactions
                    transactions = nda_parser.parse_file(f.readlines())
                    logger.debug("Successfully opened and parsed NDA file")

                    # Process transactions
                    logger.debug("Starting transaction filtering and processing")
                    for txn in transactions:
                        try:
                            # Apply filters
                            if not (txn.iban in account_numbers and
                                    txn.cents > 0 and  # Only positive amounts
                                    txn.reference and  # Must have reference number
                                    len(txn.reference) in (4,6)):  # Valid reference number length
                                continue
                        
                            # Find account by reference number
                            try:
                                account = Account.objects.get(id=str(txn.reference))
                            except Account.DoesNotExist:
                                raise ValueError(f"Account with reference ID {txn.reference} not found")

                            # Convert cents to decimal amount
                            amount = -txn.amount_decimal  # Using the new property

                            # Check for duplicates using raw data
                            duplicate_date = timezone.make_aware(
                                datetime.combine(txn.date, datetime.min.time()),
                                timezone=ZoneInfo('Europe/Helsinki')
                            )

                            if AccountEntry.objects.filter(
                                account=account,
                                date=duplicate_date,
                                amount=amount,
                                metadata__nda__unique_identifier=txn.unique_identifier # This is probably unique
                            ).exists():
                                logger.warning(f"Skipping duplicate transaction with identifier: {txn.unique_identifier}")
                                duplicates += 1
                                continue

                            # Create AccountEntry with raw data
                            entry = AccountEntry.objects.create(
                                account=account,
                                date=timezone.make_aware(
                                    datetime.combine(txn.date, datetime.min.time()),
                                    timezone=ZoneInfo('Europe/Helsinki')
                                ),
                                amount=amount,
                                description="Maksu",
                                metadata={
                                    "nda": {
                                        'unique_identifier': txn.unique_identifier,
                                        'sequence_number': txn.sequence_number,
                                        'iban': txn.iban,
                                        'bic': txn.bic,
                                        'date': txn.date.isoformat(),
                                        'ledger_date': txn.ledger_date.isoformat() if txn.ledger_date else None,
                                        'value_date': txn.value_date.isoformat() if txn.value_date else None,
                                        'payment_date': txn.payment_date.isoformat() if txn.payment_date else None,
                                        'name': txn.name,
                                        'operation': txn.operation,
                                        'reference': txn.reference,
                                        'message': txn.message,
                                        'our_reference': txn.our_reference,
                                        'recipient_iban': txn.recipient_iban,
                                        'recipient_bic': txn.recipient_bic,
                                        'receipt_flag': txn.receipt_flag,
                                        'is_receipt': txn.is_receipt
                                    }
                                }
                            )
                            count += 1
                            logger.debug(
                                f"Added transaction: {entry.date} | {amount} | "
                                f"{entry.description} | ref: {txn.reference}"
                            )

                        except Exception as e:
                            logger.error(
                                f"Error processing transaction: {str(e)} "
                                f"(date: {txn.date} | {txn.amount_decimal} | Maksu | "
                                f"ref: {txn.reference})"
                            )
                            failed += 1

            except Exception as e:
                error_msg = f"Error reading NDA file {filename}: {str(e)}"
                logger.exception(error_msg)
                continue  # Continue with next file instead of raising

            logger.info(f"In file {filename}: Imported: {count}, Failed: {failed}, Duplicates: {duplicates}")
            total_count += count
            total_failed += failed
            total_duplicates += duplicates

        logger.info(f"All NDA imports completed. Imported: {total_count}, Failed: {total_failed}, Duplicates: {total_duplicates}")

        if total_failed and not options['force']:
            logger.error("Some transactions failed to import. Use --force to import anyway")
            transaction.set_rollback(True)
