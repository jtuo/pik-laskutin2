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

    def handle(self, *args, **options):
        pattern = options['filename_pattern']
        total_count = 0
        total_failed = 0

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
        with transaction.atomic():
            for filename in files:
                logger.debug(f"Starting NDA transaction import from {filename}")
                count = 0
                failed = 0

                try:
                    with open(filename, 'r', encoding='utf-8') as f:
                        # Use the new parser to get transactions
                        transactions = nda_parser.parse_file(f.readlines())
                        logger.debug("Successfully opened and parsed NDA file")

                        # Process transactions
                        logger.debug("Starting transaction filtering and processing")
                        for txn in transactions:
                            # Apply filters
                            if not (txn.iban in account_numbers and
                                  txn.cents > 0 and  # Only positive amounts
                                  txn.reference and  # Must have reference number
                                  len(txn.reference) in (4,6)):  # Valid reference number length
                                continue

                            try:
                                # Find account by reference number
                                try:
                                    account = Account.objects.get(id=str(txn.reference))
                                except Account.DoesNotExist:
                                    logger.warning(
                                        f"Skipping transaction: Account with ID {txn.reference} "
                                        f"not found (amount: {txn.cents/100}, date: {txn.date})"
                                    )
                                    failed += 1
                                    continue

                                # Convert cents to decimal amount
                                amount = -txn.amount_decimal  # Using the new property

                                # Create AccountEntry
                                entry = AccountEntry.objects.create(
                                    account=account,
                                    date=timezone.make_aware(
                                        datetime.combine(txn.date, datetime.min.time()),
                                        timezone=ZoneInfo('Europe/Helsinki')
                                    ),
                                    amount=amount,
                                    description="Maksu"
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

                logger.info(f"File {os.path.basename(filename)} completed: {count} transactions imported, {failed} failed")
                total_count += count
                total_failed += failed

        logger.info(f"All NDA imports completed: {total_count} total transactions imported, {total_failed} total failed")