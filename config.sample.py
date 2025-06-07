from rules import make_rules

class Config:
    ALLOWED_PURPOSES = [
        "GEO", "HAR", "HIN", "KOE", "KOU", "LAN", "LAS", "LVL", "MAT", "PALO", "RAH", "SAI", "SAR",
        "SII", "TAI", "TAR", "TIL", "VLL", "VOI", "YLE", "MUU", "KIL", "TYY", "TAIKOU"
    ]

    NO_INVOICING_REFERENCE_IDS = [
    ]

    ENFORCED_ICAO_PREFIX = "EF"

    NO_INVOICING_AIRCRAFT = []

    AIRCRAFT_METADATA_MAP = {
        "1037-opeale": {"aircraft": "OH-1037", "discount_reason": "opeale"},
        "1037": {"aircraft": "OH-1037"},
        "733": {"aircraft": "OH-733"},
        "787": {"aircraft": "OH-787"},
        "650": {"aircraft": "OH-650"},
        "883": {"aircraft": "OH-883"},
        "952": {"aircraft": "OH-952"},
        "1035": {"aircraft": "OH-1035"},
        "TOW": {"aircraft": "OH-TOW"},
    }

    NDA_ACCOUNTS = ['FIXXXXXXXXXXXXXXXXX']

    RECEIVABLES_LEDGER_ACCOUNT_ID = "1422"

    LEDGER_ACCOUNT_MAP = {
        "0001": "Saamiset jäseniltä",
    }

    COURSE_DISCOUNT = [
    ]

    RULES = make_rules

    SERVICE_ACCOUNT_FILE = '../pik-laskutin-07c06bc75e3d.json'
    SENDER_ACCOUNT = 'example@example.fi'
    REPLY_TO = 'example@example.fi'
    SENDER_FROM = f'Polyteknikkojen Ilmailukerho <{SENDER_ACCOUNT}>'
    EMAIL_SUBJECT = 'PIK Lentolasku {date} viite {account_id}'

    INVOICE_TEMPLATE = '''PIK ry jäsenlaskutus, viite {{ invoice.account.id}}

---------------------------
Laskun päivämäärä: {{ invoice.created_at|date:"d.m.Y"|default:"N/A" }}

Saaja: 
Saajan tilinumero: 

Viitenumero: {{ invoice.account.id }} (PIK-viite)
Eräpäivä: {{ invoice.due_date|date:"d.m.Y" }}

Lentotilin saldo: {{ invoice.account.balance }} EUR
{% if invoice.account.balance <= 0 %}Ei maksettavaa kerholle.{% elif invoice.account.balance > 0 %}Maksettavaa: {{ total|floatformat:2 }} EUR{% endif %}
---------------------------

Hei{% if invoice.account.member.first_name %} {{ invoice.account.member.first_name}}{% endif %}!

Tässä Polyteknikkojen Ilmailukerhon lentolaskusi vuodelle 2024.

Terveisin

Tapahtumien erittely:
------------------------------------------------------------
{% for entry in entries %}{{ entry.date|date:"d.m.Y" }} {{ entry.amount|floatformat:2|rjust:8 }} EUR - {{ entry.description|safe }}
{% endfor %}------------------------------------------------------------

Yhteensä: {{ total|floatformat:2 }} EUR

'''