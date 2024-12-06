from django.db import models
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum
from loguru import logger

class Account(models.Model):
    id = models.CharField(max_length=20, primary_key=True)  # PIK reference
    member = models.ForeignKey(
        'members.Member',
        on_delete=models.SET_NULL, # Members can be deleted, but accounts should remain
        related_name='accounts',
        null=True, # There are some dangling accounts
        blank=True # Let's not enforce this at the database level
    )
    name = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'accounts'

    def __str__(self):
        return f"<Account {self.id}: {self.name}>"
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    
    @property
    def balance(self):
        # Get the latest entry with additive=False
        latest_non_additive_entry = self.entries.filter(additive=False).order_by('-date').first()
        
        if latest_non_additive_entry:
            # Sum entries from the latest non-additive entry onwards
            entries = self.entries.filter(date__gte=latest_non_additive_entry.date)
        else:
            # Sum all entries if no non-additive entry exists
            entries = self.entries.all()
        
        total = entries.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        # Ensure the total is a Decimal and format it to 2 decimal places
        return Decimal(total).quantize(
            Decimal('.01'),
            rounding=ROUND_HALF_UP
        )

class QuantizedDecimalField(models.DecimalField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_digits', 12) # Up to billions
        kwargs.setdefault('decimal_places', 2)
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        # Convert the value to a Decimal instance
        value = super().to_python(value)
        if value is None:
            return value
        
        # Round the value to the specified decimal places
        return Decimal(str(value)).quantize(
            Decimal('0.{}'.format('0' * self.decimal_places)),
            rounding=ROUND_HALF_UP
        )

    def get_prep_value(self, value):
        # Round the value before saving to database
        if value is None:
            return value
        
        value = self.to_python(value)
        return super().get_prep_value(value)

class AccountEntry(models.Model):
    date = models.DateField(db_index=True)
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='entries',
        null=False
    )
    description = models.TextField()
    amount = QuantizedDecimalField(
        help_text="Positive = charge, Negative = payment/credit"
    )
    additive = models.BooleanField(default=True)
    event = models.ForeignKey(
        'operations.BaseEvent',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='account_entries'
    )
    invoices = models.ManyToManyField(
        'Invoice',
        related_name='entries',
        blank=True
    )
    ledger_account_id = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="For mapping to external accounting system"
    )
    created_at = models.DateTimeField(default=timezone.now)
    metadata = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'account_entries'
        verbose_name = 'Entry'
        verbose_name_plural = 'Entries'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean(self):
        if self.amount is not None:
            quantized = Decimal(str(self.amount)).quantize(
                Decimal('.01'),
                rounding=ROUND_HALF_UP
            )
            if self.amount != quantized:
                raise ValidationError("Amount must have at most 2 decimal places")
        
        # Prevents associating entries with cancelled invoices
        # Does not apply to new entries
        if self.pk is not None:
            if self.invoices.filter(status='cancelled').exists():
                raise ValidationError("Cannot associate entry with cancelled invoice")
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        if self.invoices.exists():
            raise ProtectedError(
                "Cannot delete account entry that is part of an invoice.",
                obj=self
            )
        super().delete(*args, **kwargs)
    
    @classmethod
    def check_duplicate(cls):
        # TODO Implement duplicate check
        pass

    @property
    def is_modifiable(self):
        if not self.event:
            return True
        return self.event.type != 'invoice'

    @property
    def is_balance_correction(self):
        return self.force_balance is not None

    def __str__(self):
        return f"<AccountEntry {self.date}: {self.amount}>"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class AccountEntryTag(models.Model):
    entry = models.ForeignKey(
        AccountEntry,
        on_delete=models.CASCADE,
        related_name='tags'
    )
    value = models.TextField(db_index=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['value']),
        ]

        # Enforces unique tags per entry
        constraints = [
            models.UniqueConstraint(
                fields=['entry', 'value'],
                name='unique_entry_tag'
            )
        ]

        db_table = 'account_entry_tags'

    def __str__(self):
        return self.value

class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SENT = 'sent', 'Sent'
        PAID = 'paid', 'Paid'
        CANCELLED = 'cancelled', 'Cancelled'

    number = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='invoices'
    )
    due_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True
    )
    notes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'invoices'

    def clean(self):
        if not self.number:
            raise ValidationError("Invoice number cannot be empty")
        
        if self.due_date and self.due_date < self.created_at:
            raise ValidationError("Due date cannot be before creation date")
    
    def delete(self, *args, **kwargs):
        # Check if there are any associated entries
        entry_count = self.entries.count()
        if entry_count > 0:
            logger.warning(
                f"Deleting Invoice {self.number} which has {entry_count} account entries. "
                f"These entries will be dissociated but not deleted. "
                f"Total amount: {self.total_amount}"
            )
        super().delete(*args, **kwargs)

    @property
    def total_amount(self):
        return self.entries.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

    @property
    def is_overdue(self):
        return (
            self.due_date is not None and
            self.status not in [self.Status.PAID, self.Status.CANCELLED] and
            timezone.now() > self.due_date
        )

    def can_be_sent(self):
        return (
            self.status == self.Status.DRAFT and
            self.entries.exists() and
            self.due_date is not None
        )

    def __str__(self):
        return f"<Invoice {self.number}: {self.status}>"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
