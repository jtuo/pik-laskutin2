from django.core.management.base import BaseCommand
from loguru import logger
from invoicing.models import Account
from decimal import Decimal
from datetime import datetime

class Command(BaseCommand):
    help = 'Calculate and display account balance totals'

    def add_arguments(self, parser):
        parser.add_argument(
            '--end-date',
            type=str,
            help='Calculate balances up to this date (inclusive, YYYY-MM-DD)',
        )
        parser.add_argument(
            '--year',
            type=int,
            help='Calculate balances up to the end of specified year',
        )

    def handle(self, *args, **options):
        end_date = None

        # Parse end date from arguments
        if options.get('year'):
            end_date = datetime(options['year'], 12, 31).date()
            logger.debug(f"Using year end date: {end_date}")
        elif options.get('end_date'):
            try:
                end_date = datetime.strptime(options['end_date'], '%Y-%m-%d').date()
                logger.debug(f"Using specified end date: {end_date}")
            except ValueError:
                self.stderr.write('Invalid date format. Please use YYYY-MM-DD')
                return

        # Query all accounts
        accounts = Account.objects.all()
        
        # Calculate totals
        total_balance = Decimal('0.00')
        total_debt = Decimal('0.00')
        total_credit = Decimal('0.00')

        if end_date:
            logger.debug(f"Calculating balances up to {end_date}")

        for account in accounts:
            balance = account.compute_balance(end_date=end_date)
            total_balance += balance
            
            if balance < 0:
                total_debt += balance
            else:
                total_credit += balance

        # Print results with consistent date display
        date_str = f" (as of {end_date})" if end_date else ""
        self.stdout.write(f"\nAccount Balance Summary{date_str}:")
        self.stdout.write("=" * 30)
        self.stdout.write(f"Total balance:     {total_balance:10.2f} €")
        self.stdout.write(f"Total debt:        {total_debt:10.2f} €")
        self.stdout.write(f"Total credit:      {total_credit:10.2f} €")
        self.stdout.write("=" * 30)

        logger.info(f"Calculated balances for {len(accounts)} accounts{date_str}")
        
        if end_date:
            total_entries = sum(account.entries.filter(date__lte=end_date).count() for account in accounts)
            logger.debug(f"Total entries considered: {total_entries}")