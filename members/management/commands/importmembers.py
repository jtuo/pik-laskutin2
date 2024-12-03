from django.core.management.base import BaseCommand
from django.db import transaction
from loguru import logger
from members.models import Member
from invoicing.models import Account
from datetime import datetime
import csv

class Command(BaseCommand):
    help = 'Import member data from FloMembers'

    def add_arguments(self, parser):
        parser.add_argument('path', type=str, help='path of the .csv file(s)')

    def handle(self, *args, **options):
        filename = options['path']
        logger.debug(f"Importing members from {filename}")
        count = 0
        skipped = 0
        accounts_created = 0

        with open(filename, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            required_columns = {'Sukunimi', 'Etunimi', 'PIK-viite'}
            missing_columns = required_columns - set(reader.fieldnames)
            if missing_columns:
                raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

            with transaction.atomic():  # Wrap the whole import in a transaction
                for row in reader:
                    try:
                    
                        # Check if member already exists
                        member, member_created = Member.objects.get_or_create(
                            id=row['PIK-viite'],
                            defaults={
                                'first_name': row['Etunimi'],
                                'last_name': row['Sukunimi'],
                                'email': row.get('Sähköposti'),
                                'birth_date': None  # We'll set this later if provided
                            }
                        )

                        if member_created:
                            # Parse birth date if provided
                            if row.get('Syntynyt'):
                                try:
                                    # Try Finnish format first (DD.MM.YYYY)
                                    birth_date = datetime.strptime(row['Syntynyt'], '%d.%m.%Y').date()
                                except ValueError:
                                    try:
                                        # Fall back to ISO format (YYYY-MM-DD)
                                        birth_date = datetime.strptime(row['Syntynyt'], '%Y-%m-%d').date()
                                    except ValueError as e:
                                        raise ValueError(
                                            f"Invalid birth date format: {row['Syntynyt']}. "
                                            "Use DD.MM.YYYY or YYYY-MM-DD"
                                        )
                                member.birth_date = birth_date
                                member.save()

                            count += 1
                            logger.info(
                                f"Added new member: {member.name} (ID: {member.id}) "
                                f"{'with email ' + member.email if member.email else ''}"
                            )
                        else:
                            skipped += 1

                        # Create account if it doesn't exist
                        account, account_created = Account.objects.get_or_create(
                            id=row['PIK-viite'],  # Using same ID as member
                            defaults={
                                'member': member,
                                'name': f"{row['Etunimi']} {row['Sukunimi']}"
                            }
                        )

                        if account_created:
                            accounts_created += 1
                            logger.info(f"Created invoicing account for member {member.id}")

                    except Exception as e:
                        error_msg = f"Error in row {reader.line_num}: {str(e)}"
                        logger.error(error_msg)
                        raise ValueError(error_msg)

        logger.info(
            f'Successfully imported {count} members (skipped {skipped} existing) '
            f'and created {accounts_created} accounts'
        )