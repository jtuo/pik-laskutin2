from django.core.management.base import BaseCommand
from django.db import connection
from django.conf import settings
import os
import glob

class Command(BaseCommand):
    help = '☢️ Nuclear option: Destroys database and all migrations to start fresh'

    def handle(self, *args, **options):
        # Close the database connection
        connection.close()

        # If using SQLite
        if 'sqlite' in settings.DATABASES['default']['ENGINE']:
            if os.path.exists('db.sqlite3'):
                os.remove('db.sqlite3')
                self.stdout.write(self.style.SUCCESS('Removed SQLite database'))

        # Find all migration files
        for app in settings.INSTALLED_APPS:
            if '.' not in app:  # Skip built-in apps
                migration_path = f"{app}/migrations"
                if os.path.exists(migration_path):
                    # Remove all .py files except __init__.py
                    migration_files = glob.glob(f"{migration_path}/[0-9]*.py")
                    for migration in migration_files:
                        os.remove(migration)
                    # Remove all .pyc files
                    migration_files = glob.glob(f"{migration_path}/__pycache__/*")
                    for migration in migration_files:
                        os.remove(migration)
                    self.stdout.write(
                        self.style.SUCCESS(f'Removed migrations from {app}')
                    )

        # Make new migrations and apply them
        os.system('python manage.py makemigrations')
        os.system('python manage.py migrate')

        self.stdout.write(self.style.SUCCESS('Database has been reset successfully'))