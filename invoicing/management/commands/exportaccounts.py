from datetime import datetime, date
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
    help = 'Export all Accounts and their balances as .csv'

    def add_arguments(self, parser):
        parser.add_argument('filename', type=str, help='Path for .csv file')
        parser.add_argument('--valid-only', action='store_true', help='Only export accounts with a valid member')
        parser.add_argument('--end-date', type=str, help='End date, inclusive (YYYY-MM-DD)')
        parser.add_argument('--year', type=int, help='Calculate end-of-year balances for specified year')

    @transaction.atomic
    def handle(self, *args, **options):
        '''Export all Accounts and their balances as .csv
        Rows:
        - Tili
        - Nimi
        - Saldo
        - Erääntynyt
        - Viimeisin maksu
        '''
        filename = options['filename']
        valid_only = options['valid_only']
        end_date_str = options['end_date']
        year = options['year']

        # Handle end date
        end_date = None
        if end_date_str and year:
            logger.warning('Both --end-date and --year provided, using --end-date')
            
        if end_date_str:
            try:
                end_date = date.fromisoformat(end_date_str)
            except ValueError:
                logger.error(f'Invalid end date format: {end_date_str}. Use YYYY-MM-DD')
                return
        elif year:
            end_date = date(year, 12, 31)

        # Query Accounts
        if valid_only:
            accounts = Account.objects.filter(member__isnull=False)
        else:
            accounts = Account.objects.all()

        # Calculate balances for all accounts and sort
        account_balances = [(account, account.compute_balance(end_date)) for account in accounts]
        account_balances.sort(key=lambda x: x[1], reverse=True)

        # Create directory if it doesn't exist and filename has a directory part
        dirname = os.path.dirname(filename)
        if dirname:
            os.makedirs(dirname, exist_ok=True)

        # Write to CSV file
        with open(filename, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            
            # Write header
            writer.writerow(['Tili', 'Nimi', 'Saldo', 'Erääntynyt', 'Viimeisin maksu'])
            
            # Write accounts
            for account, balance in account_balances:
                writer.writerow([
                    account.id,
                    account.member.name if account.member else "",
                    f'{balance:.2f}',
                    account.overdue_since.strftime('%d.%m.%Y') if account.overdue_since else "-",
                    account.last_payment.strftime('%d.%m.%Y') if account.last_payment else "-"
                ])

        logger.info(f"Exported {len(accounts)} entries to {filename}")