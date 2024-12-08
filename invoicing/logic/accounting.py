from decimal import Decimal
from typing import Optional
from datetime import date
from django.db.models import Sum, QuerySet

class AccountBalance:
    """
    Handles balance calculations and entry filtering for invoicing.
    All accounting-related business logic should live here.
    """
    def __init__(self, account: 'Account'):
        self.account = account

    def get_latest_balance_entry(self) -> Optional['AccountEntry']:
        """Get the most recent balance entry (additive=False)"""
        return self.account.entries.filter(additive=False).order_by('-date').first()

    def get_balance(self, until_date: Optional[date] = None) -> Decimal:
        """Calculate account balance up to given date"""
        entries = self.account.entries.all()
        if until_date:
            entries = entries.filter(date__lte=until_date)

        latest_balance = self.get_latest_balance_entry()
        if latest_balance:
            entries = entries.filter(date__gte=latest_balance.date)

        return entries.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    def get_last_non_overdue_date(self) -> Optional[date]:
        """Get the last date when account had zero or negative balance"""
        if self.get_balance() <= 0:
            return None

        entries = self.get_entries_since_last_balance()
        running_balance = Decimal('0.00')
        last_non_overdue = None

        for entry in entries:
            running_balance += entry.amount
            if running_balance <= 0:
                last_non_overdue = entry.date

        if not last_non_overdue:
            latest_balance = self.get_latest_balance_entry()
            return latest_balance.date if latest_balance else entries.first().date

        return last_non_overdue

    def get_entries_since_last_balance(self) -> 'QuerySet[AccountEntry]':
        """Get all entries since the last balance entry"""
        latest_balance = self.get_latest_balance_entry()
        entries = self.account.entries.all()

        if latest_balance:
            entries = entries.filter(date__gte=latest_balance.date)

        return entries.order_by('date')

    def get_entries_for_invoice(self) -> 'QuerySet[AccountEntry]':
        """Get entries that should be included in a new invoice"""
        entries = self.account.entries.all()

        # Get cutoff date (latest of balance entry or last non-overdue date)
        balance_entry = self.get_latest_balance_entry()
        balance_date = balance_entry.date if balance_entry else None
        overdue_date = self.get_last_non_overdue_date()

        cutoff_date = max(filter(None, [balance_date, overdue_date])) if balance_date or overdue_date else None
        if cutoff_date:
            entries = entries.filter(date__gte=cutoff_date)

        return entries.order_by('date')