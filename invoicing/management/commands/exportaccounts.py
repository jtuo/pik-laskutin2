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
    help = 'Export all Accounts and their balances as .csv'

    def add_arguments(self, parser):
        parser.add_argument('filename', type=str, help='Path for .csv file')
        parser.add_argument('--valid-only', action='store_true', help='Only export accounts with a valid member')

    @transaction.atomic
    def handle(self, *args, **options):
        '''Export all Accounts and their balances as .csv
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
        valid_only = options['valid_only']

        # Query Accounts
        if valid_only:
            accounts = Account.objects.filter(member__isnull=False)
        else:
            accounts = Account.objects.all()

        # Order accounts by balance
        accounts = sorted(accounts, key=lambda a: a.balance, reverse=True)

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
            for account in accounts:
                writer.writerow([
                    account.id,
                    account.member.name if account.member else "",
                    f'{account.balance:.2f}',
                    account.overdue_since.strftime('%d.%m.%Y') if account.overdue_since else "-",
                    account.last_payment.strftime('%d.%m.%Y') if account.last_payment else "-"
                ])


        logger.info(f"Exported {len(accounts)} entries to {filename}")