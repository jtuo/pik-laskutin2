from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from datetime import datetime, timedelta, date
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
    help = 'Generate invoices for accounts'

    def add_arguments(self, parser):
        parser.add_argument('--account', type=str,
                          help='Only process this specific account')
        parser.add_argument('--year', type=int,
                          help='Invoice accounts with activity from this year')
        parser.add_argument('--period-start', type=str,
                          help='Invoice accounts with activity from this date onwards (YYYY-MM-DD)')
        parser.add_argument('--period-end', type=str,
                          help='Invoice accounts with activity until this date (YYYY-MM-DD)')
        parser.add_argument('--include-zero-balance', action='store_true',
                          help='Also send invoices for zero-balance accounts')
        parser.add_argument('--invoice-everyone', action='store_true',
                          help='Send invoice to all accounts with non-zero balance (ignores other filtering, except --account)')
        parser.add_argument('--skip-invalid', action='store_true',
                          help='Skip accounts without members')
        parser.add_argument('--delete-drafts', action='store_true',
                          help='Delete existing draft invoices before processing')
        parser.add_argument('--ignore-drafts', action='store_true',
                          help='Continue even if draft invoices exist')
        parser.add_argument('--export', action='store_true',
                          help='Export invoices to text files')
        parser.add_argument('--dry-run', action='store_true',
                          help='Preview changes without saving to database')
        parser.add_argument('--include-all-entries', action='store_true',
                          help='Include all entries that affect the balance, not just since last zero balance')

    def parse_date(self, date_str):
        """Parse a date string in YYYY-MM-DD format."""
        if not date_str:
            return None
        return datetime.strptime(date_str, '%Y-%m-%d').date()

    def get_period_bounds(self, options):
        """Get period start and end dates from options."""
        period_start = None
        period_end = None

        if options['year']:
            period_start = date(options['year'], 1, 1)
            period_end = date(options['year'], 12, 31)

        # Explicit period bounds override year
        if options['period_start']:
            period_start = self.parse_date(options['period_start'])
        if options['period_end']:
            period_end = self.parse_date(options['period_end'])

        return period_start, period_end

    def has_activity_since_last_invoice(self, account):
        """Check if account has entries since last sent invoice (inclusive date)."""
        last_sent = Invoice.objects.filter(
            account=account,
            sent_at__isnull=False
        ).order_by('-sent_at').first()

        if not last_sent:
            return False

        sent_date = last_sent.sent_at.date()
        return AccountEntry.objects.filter(
            account=account,
            date__gte=sent_date
        ).exists()

    def has_activity_in_period(self, account, period_start, period_end):
        """Check if account has entries within the specified period."""
        if not period_start and not period_end:
            return False

        query = AccountEntry.objects.filter(account=account)
        if period_start:
            query = query.filter(date__gte=period_start)
        if period_end:
            query = query.filter(date__lte=period_end)

        return query.exists()

    def should_invoice(self, account, balance, period_start=None, period_end=None,
                       invoice_everyone=False, include_zero_balance=False):
        """
        Determine if an account should receive an invoice.

        Rules:
        1. Balance > 0 -> always invoice
        2. Balance != 0 + activity since last invoice -> invoice
        3. Balance != 0 + activity in period -> invoice (when period specified)

        Modifiers:
        - invoice_everyone: skip activity checks, invoice all non-zero (or all if include_zero_balance)
        - include_zero_balance: allow zero-balance invoices (activity rules still apply)
        """
        # --invoice-everyone bypasses activity checks
        if invoice_everyone:
            if include_zero_balance:
                return True
            return balance != 0

        # Rule 1: always invoice if they owe money
        if balance > 0:
            return True

        # Rules 2 & 3 require non-zero balance (unless include_zero_balance)
        if balance == 0 and not include_zero_balance:
            return False

        # Rule 2: activity since last invoice (always applies)
        if self.has_activity_since_last_invoice(account):
            return True

        # Rule 3: activity within specified period (additive)
        if self.has_activity_in_period(account, period_start, period_end):
            return True

        return False

    def check_drafts(self, options):
        """Check for existing draft invoices and handle according to options."""
        draft_count = Invoice.objects.filter(status=Invoice.Status.DRAFT).count()

        if draft_count == 0:
            return True

        if options['delete_drafts']:
            logger.info(f"Deleting {draft_count} existing draft invoices")
            Invoice.objects.filter(status=Invoice.Status.DRAFT).delete()
            return True

        if options['ignore_drafts']:
            logger.warning(f"Proceeding despite {draft_count} existing draft invoices")
            return True

        # Stop with helpful error
        logger.error(f"Found {draft_count} existing draft invoices")
        logger.error("Use --delete-drafts to delete them, or --ignore-drafts to proceed anyway")
        return False

    def check_invalid_accounts(self, accounts, options):
        """Check for accounts without members and handle according to options."""
        invalid_accounts = accounts.filter(member__isnull=True)
        invalid_count = invalid_accounts.count()

        if invalid_count == 0:
            return accounts, True

        if options['skip_invalid']:
            logger.warning(f"Skipping {invalid_count} accounts without members")
            return accounts.filter(member__isnull=False), True

        # Categorize by severity
        with_balance = []
        zero_balance = []
        for account in invalid_accounts:
            balance = account.balance
            if balance != 0:
                with_balance.append((account, balance))
            else:
                zero_balance.append(account)

        # Stop with helpful error
        if with_balance:
            logger.error(f"Found {len(with_balance)} accounts without members that have non-zero balance:")
            for account, balance in with_balance[:10]:
                logger.error(f"  - Account {account.id}: {balance} EUR")
            if len(with_balance) > 10:
                logger.error(f"  ... and {len(with_balance) - 10} more")

        if zero_balance:
            logger.warning(f"Found {len(zero_balance)} accounts without members (all with zero balance)")

        logger.error("Use --skip-invalid to skip these accounts")
        return accounts, False

    @transaction.atomic
    def handle(self, *args, **options):
        self.options = options
        run_uuid = uuid.uuid4().hex[:4]

        logger.info(f"Generating invoices, run {run_uuid}")

        # Check for draft invoices
        if not self.check_drafts(options):
            return

        try:
            # Get accounts to process
            if options['account']:
                accounts = Account.objects.filter(id=options['account'])
                if not accounts.exists():
                    logger.error(f"Account {options['account']} not found")
                    return
            else:
                accounts = Account.objects.all()

            # Check for invalid accounts
            accounts, ok = self.check_invalid_accounts(accounts, options)
            if not ok:
                return

            # Get period bounds
            period_start, period_end = self.get_period_bounds(options)
            if period_start or period_end:
                logger.info(f"Period filter: {period_start or 'any'} to {period_end or 'any'}")

            # Determine which accounts to invoice
            accounts_to_invoice = []

            for account in tqdm(accounts, desc='Evaluating accounts'):
                balance_entries, balance = AccountBalance(account).compute()

                if self.should_invoice(
                    account, balance,
                    period_start=period_start,
                    period_end=period_end,
                    invoice_everyone=options['invoice_everyone'],
                    include_zero_balance=options['include_zero_balance']
                ):
                    accounts_to_invoice.append((account, balance_entries, balance))

            logger.info(f"Found {len(accounts_to_invoice)} accounts to invoice")

            if not accounts_to_invoice:
                logger.info("No accounts to invoice")
                return

            total = Decimal('0')

            # Create invoices
            for account, balance_entries, balance in tqdm(
                accounts_to_invoice,
                desc='Generating invoices',
            ):
                # Check for invisible entries with non-zero amounts (data integrity issue)
                invisible_with_amount = [
                    e for e in balance_entries
                    if not e.entry.visible and e.entry.amount != 0
                ]
                if invisible_with_amount:
                    logger.error(f"Account {account.id} has invisible entries with non-zero amounts:")
                    for e in invisible_with_amount[:5]:
                        logger.error(f"  - Entry {e.entry.id} on {e.entry.date}: {e.entry.amount} EUR")
                    if len(invisible_with_amount) > 5:
                        logger.error(f"  ... and {len(invisible_with_amount) - 5} more")
                    raise ValueError(
                        f"Account {account.id} has {len(invisible_with_amount)} invisible entries "
                        "with non-zero amounts. Invisible entries should not affect balance."
                    )

                # Filter out entries that have visibility set to False
                balance_entries = [entry for entry in balance_entries if entry.entry.visible]

                # Create invoice
                invoice = Invoice.objects.create(
                    account=account,
                    number=f"INV-{timezone.now().strftime('%Y%m%d')}-{account.id}-{run_uuid}",
                    due_date=timezone.now() + timedelta(days=14)
                )

                # Collect entries that contribute to the current balance
                # For negative balances (customer has credit), go back one extra zero balance
                # to provide context for how the credit was created (e.g., double payment)
                entries = []
                zeros_seen = 0
                zeros_to_skip = 1 if balance < 0 else 0

                for balance_entry in reversed(balance_entries):
                    # Stop at zero balance unless --include-all-entries is set
                    if balance_entry.balance == 0 and not options['include_all_entries']:
                        if zeros_seen >= zeros_to_skip:
                            break
                        zeros_seen += 1
                    entries.append(balance_entry.entry)

                    # Stop if the entry is not additive
                    # This is because "non-additive" entries SET the balance to a specific value
                    # Because of this, earlier entries should not be included in the invoice
                    # Otherwise, they contribute to the total of the invoice, which is incorrect
                    # It is a bit questionable if we want to even have such entries in the system
                    if not balance_entry.entry.additive:
                        break

                # Add entries to invoice
                for entry in entries:
                    entry.invoices.add(invoice)

                # Warn if no entries (can happen with zero-balance invoices)
                if not entries:
                    logger.warning(f"Invoice {invoice.number} for account {account.id} has no entries")

                logger.debug(
                    f"Created invoice {invoice.number} for {account.id} with {len(entries)} entries, total {invoice.total_amount}"
                )

                if options['export']:
                    self.export_to_file(invoice, output_dir="output")
                    logger.debug(f"Exported invoice to output/{account.id}.txt")

                total += invoice.total_amount

            logger.info(f"Total invoiced: {total} EUR")

            if options['dry_run']:
                logger.info("--dry-run is enabled, rolling back transaction")
                transaction.set_rollback(True)

        except Exception as e:
            logger.exception(f"Error creating invoices: {str(e)}")
            logger.error("Rolling back transaction")
            if self.options.get('delete_drafts'):
                logger.error("Draft invoices will be restored by transaction rollback")
            raise

    def export_to_file(self, invoice, output_dir):
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        filename = os.path.join(output_dir, f"{invoice.account.id}.txt")
        content = invoice.render(Config.INVOICE_TEMPLATE)

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
