from django.core.management.base import BaseCommand
from loguru import logger
from invoicing.models import Account
from decimal import Decimal

class Command(BaseCommand):
    help = 'Calculate and display account balance totals'

    def handle(self, *args, **options):
        # Query all accounts
        accounts = Account.objects.all()
        
        # Calculate totals
        total_balance = Decimal('0.00')
        total_debt = Decimal('0.00')
        total_credit = Decimal('0.00')

        for account in accounts:
            balance = account.balance
            total_balance += balance
            
            if balance < 0:
                total_debt += balance
            else:
                total_credit += balance

        # Print results
        self.stdout.write("\nAccount Balance Summary:")
        self.stdout.write("=" * 30)
        self.stdout.write(f"Total balance:     {total_balance:10.2f} €")
        self.stdout.write(f"Total debt:        {total_debt:10.2f} €")
        self.stdout.write(f"Total credit:      {total_credit:10.2f} €")
        self.stdout.write("=" * 30)

        logger.info(f"Calculated balances for {len(accounts)} accounts")