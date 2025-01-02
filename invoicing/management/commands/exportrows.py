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
    help = 'Export all AccountEntries as .csv'

    def add_arguments(self, parser):
        parser.add_argument('filename', type=str, help='Path for .csv file')
        parser.add_argument('--year', type=int, help='Year to export')
        parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
        parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
        parser.add_argument('--positive-only', action='store_true', help='Export only positive amounts (debts)')

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
        
        # Create directory if it doesn't exist and filename has a directory part
        dirname = os.path.dirname(filename)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        
        # Write to CSV file
        with open(filename, 'w', encoding='utf-8') as f:
            # Write header
            header = ['Date', 'Account ID', 'Description', 'Amount']
            if options.get('year'):
                header.append('Year')
            f.write(','.join(header) + '\n')
            
            # Write entries
            for entry in entries:
                row = [
                    entry.date.strftime('%Y-%m-%d'),
                    entry.account_id,
                    f'"{entry.description}"',  # Quote description to handle commas
                    str(entry.amount)
                ]
                if options.get('year'):
                    row.append(str(entry.date.year))
                f.write(','.join(row) + '\n')
        
        logger.info(f"Exported {entries.count()} entries to {filename}")

        
