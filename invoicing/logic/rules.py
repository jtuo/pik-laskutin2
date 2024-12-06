import datetime as dt
from members.models import Member

# All rules must have:
#
# "invoice" method, which takes: a source event, and produces a list of pik.billing.AccountEntry objects

from django.utils import timezone
from django.db.models import Sum

from operations.models import Flight
from invoicing.models import AccountEntry

import datetime as dt
import re
import numbers
from decimal import Decimal
from loguru import logger

class BaseRule(object):
    # Don't allow multiple ledger accounts for lines produced by a rule by default
    allow_multiple_ledger_accounts = False

class DebugRule(BaseRule):
    def __init__(self, inner_rule, debug_filter=lambda event, result: bool(result), debug_func=lambda ev, result: logger.debug(f"{ev} {result}")):
        self.inner_rule = inner_rule
        self.debug_filter = debug_filter
        self.debug_func = debug_func

    def invoice(self, event):
        result = self.inner_rule.invoice(event)
        do_debug = self.debug_filter(event, result)
        if do_debug:
            self.debug_func(event, result)
        return result

class SinceDateFilter(object):
    """
    Match events on or after the date stored in given variable in given context.

    Date must be stored in ISO 8601 format (yyyy-mm-dd)
    """
    def __init__(self, ctx, variable_id):
        self.ctx = ctx
        self.variable_id = variable_id

    def __call__(self, event):
        try:
            val = self.ctx.get(event.account_id, self.variable_id)
            limit = dt.date(*list(map(int, val.split("-"))))
            return limit <= event.date
        except Exception:
            return False

def FlightFilter(event):
    """
    Match events of type Flight
    """
    return event._meta.concrete_model == Flight

class ItemFilter(object):
    """
    Match events whose 'item' property matches given regexp.
    """
    def __init__(self, regex):
        self.regex = regex

    def __call__(self, event):
        return re.search(self.regex, event.item)
        
    def __str__(self):
        return f"ItemFilter({self.regex})"

class PeriodFilter(object):
    """
    Match events in given period
    """
    def __init__(self, period):
        """
        :param period: period to match
        :type period: pik.util.Period
        """
        self.period = period

    def __call__(self, event):
        # Handle both datetime and date objects
        event_date = event.date.date() if isinstance(event.date, dt.datetime) else event.date
        matches = event_date in self.period
        if not matches:
            logger.debug(f"PeriodFilter failed: event date {event_date} not in period {self.period}")
        return matches
        
    def __str__(self):
        start = self.period.start.strftime("%d.%m.%Y")
        end = self.period.end.strftime("%d.%m.%Y")
        return f"PeriodFilter({start} - {end})"

class AircraftFilter(object):
    """
    Match (Flight) events with one of given aircraft
    """
    def __init__(self, *aircraft):
        self.aircraft = aircraft

    def __call__(self, event):
        # Get the registration from the Aircraft model
        aircraft_reg = event.aircraft.registration if hasattr(event.aircraft, 'registration') else str(event.aircraft)
        matches = aircraft_reg in self.aircraft
        if not matches:
            logger.debug(f"AircraftFilter failed: aircraft registration '{aircraft_reg}' not in {self.aircraft}")
        return matches
        
    def __str__(self):
        return f"AircraftFilter({','.join(self.aircraft)})"

class PurposeFilter(object):
    """
    Match (Flight) events with one of given purposes of flight
    """
    def __init__(self, *purposes):
        self.purposes = purposes

    def __call__(self, event):
        return event.purpose in self.purposes
        
    def __str__(self):
        return f"PurposeFilter({','.join(self.purposes)})"

class NegationFilter(object):
    """
    Match events that don't match given filter
    """
    def __init__(self, filter):
        self.filter = filter

    def __call__(self, event):
        return not self.filter(event)
        
    def __str__(self):
        return f"NOT({self.filter})"

class TransferTowFilter(object):
    """
    Match (Flight) events with transfer_tow property
    """
    def __call__(self, event):
        #return bool(event.transfer_tow) # TODO
        return False

class SurhargeFilter(object):
    """
    Match (Flight) events with surcharge_reason set (indicates invoicing surcharge should be added)
    """
    def __str__(self):
        return "SurhargeFilter"
    def __call__(self, event):
        if hasattr(event, 'surcharge_reason'):
            return bool(event.surcharge_reason)

class PositivePriceFilter(object):
    """
    Match SimpleEvents with price 0 or greater
    """
    def __call__(self, event):
        return event.amount >= 0

class NegativePriceFilter(object):
    """
    Match SimpleEvents with price less than 0
    """
    def __call__(self, event):
        return event.amount < 0

class BirthDateFilter(object):
    """
    Match events where the pilot's age at flight time is within given range
    """
    def __init__(self, max_age):
        self.max_age = max_age
        
    def __str__(self):
        return f"BirthDateFilter(max_age={self.max_age})"

    def __call__(self, event):
        try:
            member = Member.objects.get(id=event.account_id)
            if not member.birth_date:
                logger.warning(f"No birth date set for member {event.account_id}")
                return False
                
            # Ensure we're working with date objects
            event_date = event.date.date() if isinstance(event.date, dt.datetime) else event.date
            
            # Calculate age at flight time
            age_at_flight = (
                event_date.year - member.birth_date.year - 
                ((event_date.month, event_date.day) < (member.birth_date.month, member.birth_date.day))
            )
            matches = age_at_flight <= self.max_age
            if not matches:
                logger.debug(f"BirthDateFilter failed: member age {age_at_flight} exceeds max age {self.max_age}")
            return matches
            
        except Member.DoesNotExist:
            logger.warning(f"Member {event.account_id} not found")
            return False
        except Exception as e:
            logger.exception(f"Error in BirthDateFilter for member {event.account_id}: {str(e)}")

class OrFilter(object):
    """
    Match if any of the given filters match
    """
    def __init__(self, filters):
        """
        :param filters: List of filters to check
        """
        self.filters = []
        for filter_list in filters:
            if isinstance(filter_list, list):
                # If the list contains an OrFilter, add its filters
                if len(filter_list) == 1 and isinstance(filter_list[0], OrFilter):
                    self.filters.extend(filter_list[0].filters)
                # If it's a list containing filters, add ALL of them
                else:
                    self.filters.extend(filter_list)
            else:
                self.filters.append(filter_list)

    def __call__(self, event):
        return any(f(event) for f in self.filters)
        
    def __str__(self):
        return f"OR({','.join(str(f) for f in self.filters)})"

class MemberListFilter(object):
    """
    Match events based on member reference IDs (PIK viite) using either whitelist or blacklist mode
    """
    def __init__(self, member_ids, whitelist_mode=True):
        """
        :param member_ids: Set/list of member reference IDs to match against
        :param whitelist_mode: If True, match members IN the list. If False, match members NOT in the list
        """
        self.member_ids = set(str(id) for id in member_ids)  # Convert all IDs to strings for consistency
        self.whitelist_mode = whitelist_mode

    def __call__(self, event):
        member_id = str(event.account.id)
        matches = member_id in self.member_ids if self.whitelist_mode else member_id not in self.member_ids
        if not matches:
            logger.debug(f"MemberListFilter failed: member {member_id} {'not in' if self.whitelist_mode else 'in'} list of {len(self.member_ids)} members")
        else:
            logger.info(f"MemberListFilter passed: member {member_id} {'in' if self.whitelist_mode else 'not in'} list")
        return matches
            
    def __str__(self):
        mode = "whitelist" if self.whitelist_mode else "blacklist"
        return f"MemberList({mode},{len(self.member_ids)} members)"

class MinimumDurationRule(BaseRule):
    """
    Apply minimum duration billing to flights
    """
    def __init__(self, inner_rule, aircraft_filters, min_duration, min_duration_text=None):
        """
        :param inner_rule: The rule to wrap
        :param aircraft_filters: List of aircraft filters to check if minimum billing applies
        :param min_duration: Minimum duration to bill in minutes (required)
        :param min_duration_text: Text to append to description when minimum billing applies
        """
        self.inner_rule = inner_rule
        self.aircraft_filters = aircraft_filters
        self.min_duration = min_duration
        self.min_duration_text = min_duration_text

    def invoice(self, event):
        if isinstance(event, Flight):
            # Store original duration
            orig_duration = event.duration
            # Check if minimum billing applies
            applies = (any(f(event) for f in self.aircraft_filters) and 
                      event.duration < self.min_duration)
            
            if applies:
                # Temporarily modify duration
                event.duration = self.min_duration
            
            # Get invoice lines
            lines = self.inner_rule.invoice(event)
            
            # Restore original duration
            event.duration = orig_duration
            
            # Add minimum duration text if applicable
            if applies and self.min_duration_text and lines:
                for line in lines:
                    line.description = line.description + " " + self.min_duration_text
            
            return lines
        return self.inner_rule.invoice(event)

class FlightRule(BaseRule):
    """
    Produce one AccountEntry from a Flight event if it matches all the
    filters, priced with given price, and with description derived from given template.
    """
    def __init__(self, price, ledger_account_id, filters=None, template="Lento, {aircraft}, {duration} min"):
        """
        :param price: Hourly price, in euros (as Decimal), or pricing function that takes Flight event as parameter and returns Decimal price
        :param ledger_account_id: Ledger account id of the other side of the transaction (income account)
        :param filters: Input filters (such as per-aircraft)
        :param template: Description template. Filled using string formatting with the event object's __dict__ context
        """
        if isinstance(price, numbers.Number):
            price = Decimal(str(price))
            self.pricing = lambda event: (Decimal(str(event.duration)) * price) / Decimal('60')
        else:
            self.pricing = price
        self.filters = filters if filters is not None else []
        self.template = template
        self.ledger_account_id = ledger_account_id

    def invoice(self, event):
        if event._meta.concrete_model == Flight:
            logger.debug(f"FlightRule checking filters for event: {event.__dict__}")
            # Check all filters
            for f in self.filters:
                if not f(event):
                    logger.debug(f"Filter failed: {str(f)} for {event}")
                    return []
                else:
                    logger.debug(f"Filter passed: {str(f)} for {event}")

            # Create template context with aircraft and rounded duration
            context = event.__dict__.copy()
            context['duration'] = round(context['duration'])  # Round duration for display
            if event.aircraft:
                context['aircraft'] = event.aircraft

            # Generate description and price
            description = self.template.format(**context)
            price = self.pricing(event)

            if not event.account:
                logger.warning(f"Event {event} has no account set")
                return []

            # Create invoice entry with all required fields
            entry = AccountEntry(
                account=event.account,
                date=event.date,
                description=description,
                amount=price,
                event=event,
                ledger_account_id=self.ledger_account_id
            )

            entry.save()
            
            return [entry]
        return []

class AllRules(BaseRule):
    """
    Apply all given rules, and return AccountEntrys produced by all of them
    """
    def __init__(self, inner_rules):
        """
        :param inner_rules: Apply all inner rules to the incoming event and gather their AccountEntrys into the output
        """
        self.inner_rules = inner_rules

    def invoice(self, event):
        result = []
        for rule in self.inner_rules:
            lines = rule.invoice(event)
            if lines:
                logger.debug(f"Rule {rule.__class__.__name__} produced {len(lines)} lines: {'; '.join(f'{l.description}: {l.amount}' for l in lines)}")
            result.extend(lines)
        return result

class FirstRule(BaseRule):
    """
    Apply given rules until a rule produces an AccountEntry, result is that line
    """
    def __init__(self, inner_rules):
        """
        :param inner_rules: Apply inner rules in order, return with lines from first rule that produces output
        """
        self.inner_rules = inner_rules

    def invoice(self, event):
        for rule in self.inner_rules:
            lines = rule.invoice(event)
            if lines:
                return lines
        return []

class CappedRule(BaseRule):
    def __init__(self, cap_id, cap_price, inner_rule, 
                 drop_over_cap=False, 
                 cap_description="rajattu hintakattoon"):
        self.cap_id = cap_id  # This becomes our tag identifier
        self.inner_rule = inner_rule
        self.cap_price = Decimal(str(cap_price))
        self.drop_over_cap = drop_over_cap
        self.cap_description = cap_description + f" ({self.cap_price}€)"

    def get_accumulated_amount(self, account):
        # Get all entries for this cap in the current year
        year = timezone.now().year
        return AccountEntry.objects.filter(
            account=account,
            date__year=year,
            tags__value=f"cap:{self.cap_id}"
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    def _filter_entries(self, entries):
        for entry in entries:
            accumulated = self.get_accumulated_amount(entry.account)
            if accumulated >= self.cap_price:
                if self.drop_over_cap:
                    logger.debug(f"Dropping entry '{entry.description}' (price={entry.amount}) - already at cap ({self.cap_price})")
                    entry.delete()
                logger.debug(f"Converting entry '{entry.description}' from {entry.amount} to zero price due to cap")
                entry.description += ", " + self.cap_description
                entry.amount = Decimal('0')
            else:
                if accumulated + entry.amount > self.cap_price:
                    entry.description += ", " + self.cap_description
                    entry.amount = self.cap_price - accumulated

            # Add the cap tag to track this entry
            entry.tags.create(value=f"cap:{self.cap_id}")

            entry.save()
            yield entry

    def invoice(self, event):
        entries = self.inner_rule.invoice(event)
        return list(self._filter_entries(entries))