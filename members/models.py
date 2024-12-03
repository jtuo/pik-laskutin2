from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from loguru import logger

def validate_member_id(value):
    if not value:
        raise ValidationError("Member ID cannot be empty")
    if not value.isdigit():
        raise ValidationError("Member ID must be a number")
    return value

class Member(models.Model):
    id = models.CharField(
        max_length=20,
        primary_key=True,
        validators=[validate_member_id]
    )

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(max_length=255, blank=True, null=True)
    birth_date = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'members'
    
    @property
    def name(self):
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return f"<Member {self.id}: {self.name}>"

    def clean(self):
        super().clean()

    