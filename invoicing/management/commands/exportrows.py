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
    help = 'Export all AccountEntries as .csv'

    def add_arguments(self, parser):
        parser.add_argument('filename', type=str, help='Path for .csv file')
        parser.add_argument('--year', type=int, help='Year to export')
        parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
        parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
        parser.add_argument('--positive-only', action='store_true', help='Export only positive amounts (debts)')
        parser.add_argument('--account', type=str, help='Export only entries for a specific account ID')

    @transaction.atomic
    def handle(self, *args, **options):
        '''Export all AccountEntries as .csv

        Rows:
        - Date
        - Account ID
        - Description
        - Amount
        - Year (only if --year is specified)

        Use --positive-only to export only entries with positive amounts (debts)
        Use --start-date and --end-date (YYYY-MM-DD format) to filter by date range
        Both start and end dates are inclusive, e.g:
        --start-date 2024-01-01 --end-date 2024-01-31 includes both Jan 1st and Jan 31st

        When using --year, includes all entries from January 1st through December 31st of that year
        '''
        filename = options['filename']

        # Query AccountEntries, optionally filtered by year, date range and amount
        entries = AccountEntry.objects.all().order_by('date', 'id')
        if options.get('year'):
            entries = entries.filter(date__year=options['year'])
        if options.get('start_date'):
            entries = entries.filter(date__gte=datetime.strptime(options['start_date'], '%Y-%m-%d').date())
        if options.get('end_date'):
            entries = entries.filter(date__lte=datetime.strptime(options['end_date'], '%Y-%m-%d').date())
        if options.get('positive_only'):
            entries = entries.filter(amount__gt=0)
        if options.get('account'):
            entries = entries.filter(account_id=options['account'])
        
        # Create directory if it doesn't exist and filename has a directory part
        dirname = os.path.dirname(filename)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        
        # Write to CSV file
        with open(filename, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f, delimiter=';')
            
            # Write header
            header = ['Date', 'Account ID', 'Description', 'Amount']
            if options.get('year'):
                header.append('Year')
            writer.writerow(header)
            
            # Write entries
            for entry in entries:
                row = [
                    entry.date.strftime('%Y-%m-%d'),
                    entry.account_id,
                    entry.description,
                    f'{entry.amount:.2f}'.replace('.', ',')  # Format with comma decimal separator
                ]
                if options.get('year'):
                    row.append(str(entry.date.year))
                writer.writerow(row)
        
        logger.info(f"Exported {entries.count()} entries to {filename}")

        
