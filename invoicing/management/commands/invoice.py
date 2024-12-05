from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from datetime import datetime, timedelta
import click
from loguru import logger
import sys
import uuid

from invoicing.models import Account, AccountEntry, Invoice
from operations.models import BaseEvent, Flight
from invoicing.logic.engine import create_default_engine

class Command(BaseCommand):
    help = 'Generate invoices for uninvoiced events'

    def add_arguments(self, parser):
        parser.add_argument('account_id', nargs='?', type=str,
                          help='Optional account ID to invoice')
        parser.add_argument('--start-date', type=str,
                          help='Start date for events (YYYY-MM-DD)')
        parser.add_argument('--end-date', type=str,
                          help='End date for events (YYYY-MM-DD)')
        parser.add_argument('--export', action='store_true',
                          help='Export invoices to text files')
        parser.add_argument('--debug', action='store_true',)
        parser.add_argument('--group-entries', action='store_true',
                          help='Group entries by type in export')

    @transaction.atomic
    def handle(self, *args, **options):
        self.options = options
        if not options['debug']:
            logger.remove()
            logger.add(sys.stderr, level="INFO")
        
        run_uuid = uuid.uuid4().hex[:4]

        logger.info(f"Generating invoices for uninvoiced events, run {run_uuid}")

        try:
            # Parse dates if provided
            start_date = None
            end_date = None
            if options['start_date']:
                start_date = timezone.make_aware(datetime.strptime(options['start_date'], '%Y-%m-%d'))
            if options['end_date']:
                end_date = timezone.make_aware(datetime.strptime(options['end_date'], '%Y-%m-%d'))

            # Build query for uninvoiced events (Flights only)
            query = Flight.objects.filter(
                account_entries__isnull=True
            )
            
            logger.debug(f"Found {query.count()} uninvoiced events")

            if options['account_id']:
                query = query.filter(account_id=options['account_id'])
            if start_date:
                query = query.filter(date__gte=start_date)
            if end_date:
                query = query.filter(date__lte=end_date)

            # Order by account and date
            events = query.order_by('account_id', 'date')

            if not events.exists():
                logger.error("No uninvoiced events found matching criteria")
                return

            # Process events through rule engine
            engine = create_default_engine()
            engine.process_events(events)

            # Look up all accounts with outstanding balances
            accounts_with_outstanding_balances = []
            for account in Account.objects.all():
                if account.balance > 0:
                    accounts_with_outstanding_balances.append(account)

            logger.info(f"Found {len(accounts_with_outstanding_balances)} accounts with outstanding balances")

            total = Decimal('0')

            # Create actual invoices
            for account in accounts_with_outstanding_balances:

                # Create invoice
                invoice = Invoice.objects.create(
                    account=account,
                    number=f"INV-{timezone.now().strftime('%Y%m%d')}-{account.id}-{run_uuid}",
                    due_date=timezone.now() + timedelta(days=14)
                )

                # Find and add any uninvoiced AccountEntries for this account
                uninvoiced_entries = AccountEntry.objects.filter(
                    account=account,
                    invoices__isnull=True
                )

                # Add entries to invoice using many-to-many relationship
                for entry in uninvoiced_entries:
                    entry.invoices.add(invoice)

                # If there are no entries, it means that the account has an outstanding balance
                # We must include all the entries in the invoice since the last balance entry
                # If there is no balance entry, include all entries
                if not uninvoiced_entries.exists():

                    logger.warning(f"Account {account.id} has an outstanding balance but no entries to invoice")

                    latest_balance = AccountEntry.objects.filter(
                        account=account,
                        additive=False
                    ).order_by('date').last()

                    if latest_balance:
                        uninvoiced_entries = AccountEntry.objects.filter(
                            account=account,
                            date__gte=latest_balance.date
                        )
                    else:
                        uninvoiced_entries = AccountEntry.objects.filter(
                            account=account
                        )

                    # Add these entries to invoice too
                    for entry in uninvoiced_entries:
                        entry.invoices.add(invoice)
                

                self.stdout.write(
                    f"Created invoice {invoice.number} for {account.id} with {len(uninvoiced_entries)} entries"
                )

                if options['export']:
                    total += self.export_invoice(invoice)
                    self.stdout.write(f"Exported invoice to output/{account.id}.txt")
            
            logger.info(f"Total invoiced: {total} EUR")

        except Exception as e:
            logger.exception(f"Error creating invoices: {str(e)}")
            raise

    def export_invoice(self, invoice):
        self.options = self.options if hasattr(self, 'options') else {}
        """Export an invoice to a text file."""
        import os
        output_dir = "output"
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        filename = os.path.join(output_dir, f"{invoice.account.id}.txt")
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"Invoice {invoice.number}\n")
            f.write(f"Account: {invoice.account.id} - {invoice.account.name}\n")
            created_date = invoice.created_at.strftime('%d.%m.%Y') if invoice.created_at else 'N/A'
            due_date = invoice.due_date.strftime('%d.%m.%Y') if invoice.due_date else 'N/A'
            f.write(f"Date: {created_date}\n")
            f.write(f"Due date: {due_date}\n\n")

            entries = invoice.entries.all()
            
            # Find and filter by latest balance entry
            latest_balance = entries.filter(additive=False).order_by('date').last()
            if latest_balance:
                entries = entries.filter(date__gte=latest_balance.date)
            
            total = Decimal('0')
            
            if not self.options.get('group_entries'):
                # Original sorting by date only
                entries = entries.order_by('date')
                f.write("Items:\n")
                f.write("-" * 60 + "\n")
                for entry in entries:
                    date_str = entry.date.strftime('%d.%m.%Y') if entry.date else 'N/A'
                    f.write(f"{date_str} {entry.amount:>8} EUR - {entry.description}\n")
                    total += entry.amount
            else:
                # Group entries by type
                entry_groups = {
                    'Lentomaksut': [],
                    'Kalustomaksut': [],
                    'Kulukorvaukset': [],
                    'Muut tapahtumat': []
                }
                
                for entry in entries.order_by('date'):
                    desc_lower = entry.description.lower()
                    if 'lento' in desc_lower:
                        entry_groups['Lentomaksut'].append(entry)
                    elif 'kalusto' in desc_lower:
                        entry_groups['Kalustomaksut'].append(entry)
                    elif 'kulukorvaus' in desc_lower:
                        entry_groups['Kulukorvaukset'].append(entry)
                    else:
                        entry_groups['Muut tapahtumat'].append(entry)
                
                # Only write header if we have any entries
                if any(group_entries for group_entries in entry_groups.values()):
                    f.write("Items:\n")
                    first_group = True
                    for group_name, group_entries in entry_groups.items():
                        if group_entries:
                            if first_group:
                                first_group = False
                            else:
                                f.write("\n")  # Add spacing between groups
                            f.write(group_name + ":\n")
                            f.write("-" * 60 + "\n")
                            group_total = Decimal('0')
                            for entry in group_entries:
                                date_str = entry.date.strftime('%d.%m.%Y') if entry.date else 'N/A'
                                f.write(f"{date_str} {entry.amount:>8} EUR - {entry.description}\n")
                                total += entry.amount
                                group_total += entry.amount
                            f.write(f"Yhteensä: {group_total:>9} EUR\n")
            f.write("-" * 60 + "\n")
            f.write(f"\nMaksettavaa: {total} EUR\n")

            return total
