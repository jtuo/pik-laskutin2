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

class Command(BaseCommand):
    help = 'Process all events with no associated AccountEntries'

    @transaction.atomic
    def handle(self, *args, **options):
        self.options = options

        logger.info("Processing all events with no associated AccountEntries")

        # Build query for uninvoiced events (Flights only)
        query = Flight.objects.filter(
            account_entries__isnull=True
        )
        
        # Order by account and date
        events = query.order_by('account_id', 'date')

        if not events.exists():
            logger.info("No new events to process")
            return
        
        logger.info(f"Found {events.count()} events to process")

        # Process events through rule engine
        engine = create_default_engine()
        engine.process_events(events)

        logger.info("All events processed")
