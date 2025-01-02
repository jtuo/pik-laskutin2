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
import csv

class Command(BaseCommand):
    help = 'Export all AccountEntries as .csv for Kitsas software'

    def add_arguments(self, parser):
        parser.add_argument('filename', type=str, help='Path for .csv file')
        parser.add_argument('--year', type=int, help='Year to export')
        parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
        parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')

    @transaction.atomic
    def handle(self, *args, **options):
        '''Export all AccountEntries as .csv for Kitsas software
        Rows:
        - Tosite
        - Päivämäärä
        - Nro
        - Tili
        - Debet
        - Kredit
        - Selite
        '''
        filename = options['filename']

        # Query AccountEntries, optionally filtered by year and amount
        # Only export entries with amount >= 0
        entries = AccountEntry.objects.filter(amount__gte=0).order_by('date', 'id')

        if options.get('year'):
            entries = entries.filter(date__year=options['year'])
        if options.get('start_date'):
            entries = entries.filter(date__gte=datetime.strptime(options['start_date'], '%Y-%m-%d').date())
        if options.get('end_date'):
            entries = entries.filter(date__lte=datetime.strptime(options['end_date'], '%Y-%m-%d').date())

        # Create directory if it doesn't exist and filename has a directory part
        dirname = os.path.dirname(filename)
        if dirname:
            os.makedirs(dirname, exist_ok=True)

        # Write to CSV file
        with open(filename, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            
            # Write header
            writer.writerow(['Tosite', 'Päivämäärä', 'Nro', 'Tili', 'Debet', 'Kredit', 'Selite'])
            
            # Write entries
            for entry in entries:
                if entry.ledger_account_id not in Config.LEDGER_ACCOUNT_MAP:
                    logger.error(f"Skipping entry {entry.id} with unknown ledger account {entry.ledger_account_id}")
                    logger.error(f"{entry}, {entry.description}")
                    logger.error(f"Please add ledger account {entry.ledger_account_id} to config.LEDGER_ACCOUNT_MAP")
                
                # Format amount like: XX.XX
                amount = f'{entry.amount:.2f}'

                # First row
                writer.writerow([
                    entry.id,
                    entry.date.strftime('%d.%m.%Y'),  # Format as DD.MM.YYYY
                    "1422",
                    "Saamiset jäseniltä",
                    amount,
                    "",
                    f'Lentolasku, {entry.account.id}: {entry.description}'
                ])

                # Second row
                writer.writerow([
                    entry.id,
                    entry.date.strftime('%d.%m.%Y'),  # Format as DD.MM.YYYY
                    entry.ledger_account_id,
                    Config.LEDGER_ACCOUNT_MAP[entry.ledger_account_id]
                    if entry.ledger_account_id in Config.LEDGER_ACCOUNT_MAP else "",
                    "",
                    amount,
                    f'Lentolasku, {entry.account.id}: {entry.description}'
                ])

        logger.info(f"Exported {entries.count()} entries to {filename}")