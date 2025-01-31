from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from operations.models import BaseEvent
from invoicing.models import Account, AccountEntry
from typing import List, Dict
from config import Config
from loguru import logger
from tqdm import tqdm

class RuleEngine:
    def __init__(self):
        self.rules = []

    def add_rules(self, rules):
        self.rules.extend(rules)

    @transaction.atomic
    def process_event(self, event: BaseEvent) -> List:
        entries = []

        if event.reference_id in Config.NO_INVOICING_REFERENCE_IDS:
            logger.debug(f"Skipping event {event} due to reference ID {event.reference_id}")
            return entries
        
        for rule in self.rules:
            new_entries = rule.invoice(event)
            for entry in new_entries:
                if isinstance(entry, AccountEntry):
                    entry.save()
                    event.account_entries.add(entry)
                entries.append(entry)
        
        if not entries:
            logger.warning(f"No entries were generated for event {event}")
        
        return entries

    @transaction.atomic
    def process_events(self, events: List[BaseEvent]) -> Dict[Account, List]:
        logger.info(f"Processing {len(events)} events")
        results: Dict[Account, List] = {}
        for event in tqdm(events, miniters=10, desc='Processing events'):
            account = event.account
            entries = self.process_event(event)
            if entries:
                if account not in results:
                    results[account] = []
                results[account].extend(entries)
        return results
    
    @transaction.atomic
    def refund_event(self, event: BaseEvent) -> AccountEntry:
        """Creates a refund entry that cancels out all charges for an event"""
        if event.has_been_refunded:
            logger.warning(f"Event {event} has already been refunded")
            return None

        # Get all existing charges
        charges = event.account_entries.filter(additive=True)
        total_amount = charges.aggregate(total=Sum('amount'))['total'] or 0
        
        if total_amount == 0:
            logger.warning(f"No charges found to refund for event {event}")
            return None

        # Create refund entry
        refund = AccountEntry(
            account=event.account,
            date=timezone.now(),
            amount=-total_amount,  # Negative to cancel out charges
            description=f"Korjaus: Hyvitys {event}",
            event=event
        )

        refund.save()
        
        # Link refund to event
        event.refund_entry = refund
        event.save()
        
        logger.info(f"Created refund entry {refund} for event {event}")
        return refund

def create_default_engine() -> RuleEngine:
    """Create a RuleEngine with default rules"""
    engine = RuleEngine()

    engine.add_rules(Config.RULES())
    
    return engine
