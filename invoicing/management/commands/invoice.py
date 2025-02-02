from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from datetime import datetime, timedelta
from loguru import logger
from tqdm import tqdm
import os
import uuid

from invoicing.models import Account, AccountEntry, Invoice
from operations.models import BaseEvent, Flight
from invoicing.logic.engine import create_default_engine
from invoicing.logic.accounting import AccountBalance

from config import Config

class Command(BaseCommand):
    help = 'Generate invoices for uninvoiced events'

    def add_arguments(self, parser):
        parser.add_argument('account_id', nargs='?', type=str,
                          help='Account ID to invoice')
        parser.add_argument('--all-accounts', action='store_true',
                          help='Invoice all accounts with uninvoiced entries')
        parser.add_argument('--export', action='store_true',
                          help='Export invoices to text files')
        parser.add_argument('--delete-drafts', action='store_true',
                            help='Delete draft invoices before export')
        parser.add_argument('--uninvoiced-entries-only', action='store_true',
                            help='Only invoice entries that have not been invoiced yet')
        parser.add_argument('--dry-run', action='store_true',
                            help='Database changes are rolled back after processing')
        parser.add_argument('--valid-accounts-only', action='store_true',
                            help='Only process accounts with an associated member')
        parser.add_argument('--minimum-balance', type=float,
                            help='Minimum balance for an account to be invoiced')

    @transaction.atomic
    def handle(self, *args, **options):
        self.options = options
        
        run_uuid = uuid.uuid4().hex[:4]

        logger.info(f"Generating invoices for uninvoiced AccountEntries, run {run_uuid}")

        if options['delete_drafts']:
            logger.info("Deleting existing draft invoices")
            Invoice.objects.filter(status=Invoice.Status.DRAFT).delete()

        try:
            # Look up all accounts with outstanding balances
            accounts_with_outstanding_balances = []
            
            if options['account_id']:
                accounts = Account.objects.filter(id=options['account_id'])
            else:
                accounts = Account.objects.all()
                
            if options['valid_accounts_only']:
                accounts = accounts.filter(member__isnull=False)
            
            if options['uninvoiced_entries_only']:
                for account in accounts:
                    entries = AccountEntry.objects.filter(account=account, invoices__isnull=True)
                    if entries.exists():
                        accounts_with_outstanding_balances.append((account, entries, account.balance))
            else:
                for account in accounts:
                    balance_entries, balance = AccountBalance(account).compute()
                    if balance > 0:
                        accounts_with_outstanding_balances.append((account, balance_entries, balance))

            logger.info(f"Found {len(accounts_with_outstanding_balances)} accounts with outstanding balances")

            total = Decimal('0')

            # Create actual invoices
            for account, balance_entries, balance in tqdm(
                accounts_with_outstanding_balances,
                desc='Generating invoices',
                ):
                
                # Skip accounts with balance below minimum if set
                if options['minimum_balance'] and balance < Decimal(str(options['minimum_balance'])):
                    logger.warning(f"Skipping account {account.id} with balance {balance} (below minimum {options['minimum_balance']})")
                    continue

                # Filter out entries that have visibility set to False
                balance_entries = [entry for entry in balance_entries if entry.entry.visible]
                
                # Create invoice
                invoice = Invoice.objects.create(
                    account=account,
                    number=f"INV-{timezone.now().strftime('%Y%m%d')}-{account.id}-{run_uuid}",
                    due_date=timezone.now() + timedelta(days=14)
                )
                
                if options['uninvoiced_entries_only']:
                    # Filter out entries that have already been invoiced
                    entries = balance_entries
                    for entry in entries:
                        entry.invoices.add(invoice)
                else:
                    # We need to invoice all entries since the last zero balance
                    entries = []
                    
                    # Find last entry that was at zero balance
                    for balance_entry in reversed(balance_entries):
                        if balance_entry.balance == 0:
                            break
                        entries.append(balance_entry.entry)

                        # Stop if the entry is not additive
                        # This is because "non-additive" entries SET the balance to a specific value 
                        # Because of this, earlier entries should not be included in the invoice
                        # Otherwise, they contribute to the total of the invoice, which is incorrect
                        # It is a bit questionable if we want to even have such entries in the system
                        if not balance_entry.entry.additive:
                            break

                    # Add entries to invoice using many-to-many relationship
                    for entry in entries:
                        entry.invoices.add(invoice)
                
                # There should be at least one entry to invoice
                if not entries:
                    raise ValueError(f"Account {account.id} has an outstanding balance but no entries to invoice")

                logger.debug(
                    f"Created invoice {invoice.number} for {account.id} with {len(entries)} entries"
                )

                if options['export']:
                    self.export_to_file(invoice, output_dir="output")
                    logger.debug(f"Exported invoice to output/{account.id}.txt")
                
                total += invoice.total_amount

                # Verify that the total_amount matches the balance calculations
                # This makes sure that the invoice contains all relevant entries

                if invoice.total_amount != balance:
                    if options['uninvoiced_entries_only']:
                        logger.warning(
                            f"Account {account.id} has an outstanding balance of {balance} that is not invoiced",
                            f"Total amount of invoice {invoice.number} is {invoice.total_amount}"
                            "This is expected if the '--uninvoiced-entries-only' flag is set"
                        )
                    else:
                        logger.error(
                            "The logic of the accounting system is flawed. Please investigate.",
                            "Contact the 'developers', or better yet, fix it yourself :D",
                            "This can also happen if there are entries in the invoice with visible=False."
                        )
                        raise ValueError(
                            f"Total amount of invoice {invoice.number} ({invoice.total_amount}) "
                            f"does not match account balance ({account.balance})"
                        )
            
            logger.info(f"Total invoiced: {total} EUR")

            if options['dry_run']:
                logger.info("--dry-run is enabled, rolling back transaction")
                transaction.set_rollback(True)

        except Exception as e:
            logger.exception(f"Error creating invoices: {str(e)}")
            if self.options.get('delete_drafts'):
                logger.error("Rolling back transaction and restoring draft invoices")
            raise
    
    def export_to_file(self, invoice, output_dir):
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        filename = os.path.join(output_dir, f"{invoice.account.id}.txt")
        content = invoice.render(Config.INVOICE_TEMPLATE)
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)