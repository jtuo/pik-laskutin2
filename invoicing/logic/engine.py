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
        lines = []

        if event.reference_id in Config.NO_INVOICING_REFERENCE_IDS:
            logger.debug(f"Skipping event {event} due to reference ID {event.reference_id}")
            return lines
        
        for rule in self.rules:
            new_lines = rule.invoice(event)
            for line in new_lines:
                if isinstance(line, AccountEntry):
                    line.save()
                    event.account_entries.add(line)
                lines.append(line)
        return lines

    @transaction.atomic
    def process_events(self, events: List[BaseEvent]) -> Dict[Account, List]:
        results: Dict[Account, List] = {}
        for event in tqdm(events, miniters=10):
            account = event.account
            lines = self.process_event(event)
            if lines:
                if account not in results:
                    results[account] = []
                results[account].extend(lines)
        return results

def create_default_engine() -> RuleEngine:
    """Create a RuleEngine with default rules"""
    engine = RuleEngine()

    engine.add_rules(Config.RULES())
    
    return engine
