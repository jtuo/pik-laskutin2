from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, TYPE_CHECKING
from datetime import date
from django.db.models import Sum, QuerySet

if TYPE_CHECKING:
    from invoicing.models import Account, AccountEntry

@dataclass
class BalanceEntry:
    """Represents a balance at a specific point in time"""
    date: date
    balance: Decimal
    entry: 'AccountEntry'  # Forward reference

class AccountBalance:
    """
    Handles balance calculations and entry filtering for invoicing.
    All accounting-related business logic should live here.
    """
    def __init__(self, account: 'Account'):
        self.account = account

    def compute(self, until_date: Optional[date] = None) -> tuple[list[BalanceEntry], Decimal]:
        """
        Calculate running balances and final balance up to given date.
        Returns a tuple of (list of BalanceEntry objects, final balance).
        
        The BalanceEntry objects represent the running balance after each entry.
        If until_date is provided, only entries up to that date are included.
        """
        entries = self.account.entries.all().order_by('date')
        if until_date:
            entries = entries.filter(date__lte=until_date)
            
        running_balances = []
        current_balance = Decimal('0.00')
        
        for entry in entries:
            current_balance += entry.amount
            running_balances.append(BalanceEntry(
                date=entry.date,
                balance=current_balance,
                entry=entry
            ))
            
            # If this is a balance entry (additive=False), reset the running total
            if not entry.additive:
                current_balance = entry.amount
        
        final_balance = current_balance if running_balances else Decimal('0.00')
        final_balance = final_balance.quantize(
            Decimal('.01'),
            rounding=ROUND_HALF_UP
        )

        return running_balances, final_balance

    def get_last_non_overdue_date(self) -> Optional[date]:
        """Get the last date when account had zero or negative balance"""
        balances, _ = self.compute()

        # If there are no balances, we're not overdue
        if not balances:
            return None
            
        # If current balance is not positive, we're not overdue
        if balances[-1].balance <= 0:
            return None
            
        # Find the date of the first entry where balance was > 0
        for balance_entry in balances:
            if balance_entry.balance > 0:
                return balance_entry.date
                
        # If we never had a non-positive balance, return the first entry date
        return balances[0].date
