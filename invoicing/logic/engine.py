from django.db import transaction
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
        for event in tqdm(events, miniters=10):
            account = event.account
            entries = self.process_event(event)
            if entries:
                if account not in results:
                    results[account] = []
                results[account].extend(entries)
        return results

def create_default_engine() -> RuleEngine:
    """Create a RuleEngine with default rules"""
    engine = RuleEngine()

    engine.add_rules(Config.RULES())
    
    return engine
