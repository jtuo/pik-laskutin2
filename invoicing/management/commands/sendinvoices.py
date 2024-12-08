from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from datetime import datetime, timedelta
from loguru import logger
from tqdm import tqdm

from invoicing.models import Account, AccountEntry, Invoice
from operations.models import BaseEvent, Flight
from invoicing.logic.engine import create_default_engine

from googleapiclient.discovery import build
from google.oauth2 import service_account
from email.mime.text import MIMEText
import base64

from config import Config

class Command(BaseCommand):
    help = 'Send invoices to customers'

    def add_arguments(self, parser):
        parser.add_argument('account_id', nargs='?', type=str, help='Account ID to invoice')
        parser.add_argument('--all-accounts', action='store_true', help='Invoice all accounts with uninvoiced entries')

    def handle(self, *args, **options):
        if options['account_id']:
            accounts = Account.objects.filter(id=options['account_id'])
        elif options['all_accounts']:
            accounts = Account.objects.all()
        else:
            accounts = []
        
        if not accounts:
            raise ValueError('No accounts to send invoices for')

        # Find all invoices that are in DRAFT status for the selected accounts
        invoices = list(Invoice.objects.filter(account__in=accounts, status=Invoice.Status.DRAFT))

        if not invoices:
            raise ValueError('No invoices to send')

        # Load the service account credentials
        credentials = service_account.Credentials.from_service_account_file(
            Config.SERVICE_ACCOUNT_FILE,
            scopes=['https://www.googleapis.com/auth/gmail.send'],
            subject=Config.SENDER_ACCOUNT
        )

        service = build('gmail', 'v1', credentials=credentials)

        for invoice in tqdm(invoices, desc='Sending invoices'):
            with transaction.atomic():
                logger.info(f'Sending invoice {invoice.id} for account {invoice.account.id}')

                if not invoice.account.member.email:
                    raise ValueError(f'Account {invoice.account.id} has no email address')

                body = invoice.render(Config.INVOICE_TEMPLATE)

                # Create the email message
                message = MIMEText(body)
                message['to'] = invoice.account.member.email

                invoice_data = {
                    'account_id': invoice.account.id,
                    'date': invoice.created_at.strftime('%m/%Y')
                }

                message['subject'] = Config.EMAIL_SUBJECT.format(**invoice_data)
                message['from'] = Config.SENDER_ACCOUNT
                message['reply-to'] = Config.REPLY_TO

                # Encode the message
                raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

                sent_message = service.users().messages().send(
                    userId='me',
                    body={'raw': raw_message}
                ).execute()

                logger.info(f'Email sent: {sent_message["id"]} to {message["to"]}')

                # Update the invoice status
                invoice.status = Invoice.Status.SENT
                invoice.sent_at = timezone.now()
                invoice.save()




