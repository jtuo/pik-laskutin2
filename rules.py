from invoicing.logic.rules import (
    FlightRule, AircraftFilter, PeriodFilter, CappedRule, AllRules, FirstRule, 
    OrFilter, PurposeFilter, InvoicingChargeFilter, TransferTowFilter, 
    PositivePriceFilter, NegativePriceFilter, BirthDateFilter, 
    MinimumDurationRule, MemberListFilter
)

import datetime as dt
from decimal import Decimal
from loguru import logger

def make_rules():
    # Configuration
    YEAR = 2024

    ACCT_PURSI_KEIKKA = 3220
    ACCT_TOW = 3130
    ACCT_1037 = 3150 # Lentotuntitulot jäseniltä
    ACCT_1037_OPEALE = 3150 # Lentotuntitulot jäseniltä
    ACCT_TOWING = 3170 # Muut lentotoiminnan tulot
    ACCT_PURSI_INSTRUCTION = 3470 # Muut tulot koulutustoiminnasta
    ACCT_KALUSTO = 3010
    ACCT_LASKUTUSLISA = 3610 # Hallinnon tulot

    ID_PURSI_CAP_2024 = f"pursi_hintakatto_{YEAR}"
    ID_KALUSTOMAKSU_CAP_2024 = f"kalustomaksu_hintakatto_{YEAR}"

    # Kurssialennus
    from config import Config # Avoid circular import
    member_ids = Config.COURSE_DISCOUNT
    if len(member_ids) > 0: logger.warning(f"Course is active for {len(member_ids)} members!")
    
    F_YOUTH = [BirthDateFilter(25)]
    F_KURSSI = [MemberListFilter(member_ids, whitelist_mode=True)]

    F_FK = [AircraftFilter("OH-650")]
    F_FM = [AircraftFilter("OH-787")]
    F_FQ = [AircraftFilter("OH-733")]
    F_FY = [AircraftFilter("OH-883")]
    F_FI = [AircraftFilter("OH-1035")]
    F_DG = [AircraftFilter("OH-952")]
    F_TOW = [AircraftFilter("OH-TOW")]
    F_1037 = [AircraftFilter("OH-1037")]
    F_1037_OPEALE = [AircraftFilter("OH-1037-opeale")]

    F_MOTTI = [OrFilter([F_TOW + F_1037+ F_1037_OPEALE])]
    F_PURTSIKKA = [OrFilter([F_FK + F_FM + F_FQ + F_FY + F_FI + F_DG])]
    F_KAIKKI_KONEET = [OrFilter([F_MOTTI + F_PURTSIKKA])]

    F_LASKUTUSLISA = [InvoicingChargeFilter()]
    F_TRANSFER_TOW = [TransferTowFilter()]

    rules = [
        # OH-TOW
        FirstRule([
            # Nuorisoalennus + siirtohinaus
            MinimumDurationRule(
                FlightRule(Decimal('122') * Decimal('0.75'), ACCT_TOWING, 
                          F_TOW + F_TRANSFER_TOW + F_YOUTH,
                          "Siirtohinaus {aircraft}, {duration} min (nuorisoalennus 25%)"),
                F_MOTTI, 15, "(minimilaskutus 15 min)"),
            
            # Nuorisoalennus
            MinimumDurationRule(
                FlightRule(122 * 0.75, ACCT_TOW,
                          F_TOW + F_YOUTH,
                          "Lento {aircraft}, {duration} min (nuorisoalennus 25%)"),
                F_MOTTI, 15, "(minimilaskutus 15 min)"),
            
            # Siirtohinaus
            MinimumDurationRule(
                FlightRule(Decimal('122'), ACCT_TOWING,
                          F_TOW + F_TRANSFER_TOW,
                          "Siirtohinaus {aircraft}, {duration} min"),
                F_MOTTI, 15, "(minimilaskutus 15 min)"),
            
            # Normaalilento
            MinimumDurationRule(
                FlightRule(122, ACCT_TOW,
                          F_TOW,
                          "Lento {aircraft}, {duration} min"),
                F_MOTTI, 15, "(minimilaskutus 15 min)")
        ]),

        # OH-1037
        FirstRule([
            # Nuorisoalennus
            MinimumDurationRule(
                FlightRule(Decimal('113') * Decimal('0.75'), ACCT_1037,
                          F_1037 + F_YOUTH,
                          "Lento {aircraft}, {duration} min (nuorisoalennus 25%)"),
                F_MOTTI, 15, "(minimilaskutus 15 min)"),
            
            # Normaalilento
            MinimumDurationRule(
                FlightRule(Decimal('113'), ACCT_1037,
                          F_1037,
                          "Lento {aircraft}, {duration} min"),
                F_MOTTI, 15, "(minimilaskutus 15 min)")
        ]),

        # OH-1037 opeale
        FlightRule(Decimal('65'), ACCT_1037_OPEALE, F_1037_OPEALE, "Lento {duration} min (opealennus)"),

        # Purtsikat
        CappedRule(ID_PURSI_CAP_2024, Decimal('1250'),
        AllRules([
            # Purtsikat
            FirstRule([
                FlightRule(Decimal('18') * Decimal('0.75'), ACCT_PURSI_KEIKKA, F_FK + F_YOUTH, "Lento {aircraft}, {duration} min (nuorisoalennus 25%)"),
                FlightRule(Decimal('18') * Decimal('0.75'), ACCT_PURSI_KEIKKA, F_FK + F_KURSSI, "Lento {aircraft}, {duration} min (kurssialennus 25%)"),
                FlightRule(Decimal('18'), ACCT_PURSI_KEIKKA, F_FK)
            ]),
            FirstRule([
                FlightRule(Decimal('26') * Decimal('0.75'), ACCT_PURSI_KEIKKA, F_FM + F_YOUTH, "Lento {aircraft}, {duration} min (nuorisoalennus 25%)"),
                FlightRule(Decimal('26') * Decimal('0.75'), ACCT_PURSI_KEIKKA, F_FM + F_KURSSI, "Lento {aircraft}, {duration} min (kurssialennus 25%)"),
                FlightRule(Decimal('26'), ACCT_PURSI_KEIKKA, F_FM)
            ]),
            FirstRule([
                FlightRule(Decimal('28') * Decimal('0.75'), ACCT_PURSI_KEIKKA, F_FQ + F_YOUTH, "Lento {aircraft}, {duration} min (nuorisoalennus 25%)"),
                FlightRule(Decimal('28') * Decimal('0.75'), ACCT_PURSI_KEIKKA, F_FQ + F_KURSSI, "Lento {aircraft}, {duration} min (kurssialennus 25%)"),
                FlightRule(Decimal('28'), ACCT_PURSI_KEIKKA, F_FQ)
            ]),
            FirstRule([
                FlightRule(Decimal('29') * Decimal('0.75'), ACCT_PURSI_KEIKKA, F_FI + F_YOUTH, "Lento {aircraft}, {duration} min (nuorisoalennus 25%)"),
                FlightRule(Decimal('29') * Decimal('0.75'), ACCT_PURSI_KEIKKA, F_FI + F_KURSSI, "Lento {aircraft}, {duration} min (kurssialennus 25%)"),
                FlightRule(Decimal('29'), ACCT_PURSI_KEIKKA, F_FI)
            ]),
            FirstRule([
                FlightRule(Decimal('36') * Decimal('0.75'), ACCT_PURSI_KEIKKA, F_FY + F_YOUTH, "Lento {aircraft}, {duration} min (nuorisoalennus 25%)"),
                FlightRule(Decimal('36') * Decimal('0.75'), ACCT_PURSI_KEIKKA, F_FY + F_KURSSI, "Lento {aircraft}, {duration} min (kurssialennus 25%)"),
                FlightRule(Decimal('36'), ACCT_PURSI_KEIKKA, F_FY)
            ]),
            FirstRule([
                FlightRule(Decimal('44') * Decimal('0.75'), ACCT_PURSI_KEIKKA, F_DG + F_YOUTH, "Lento {aircraft}, {duration} min (nuorisoalennus 25%)"),
                FlightRule(Decimal('44') * Decimal('0.75'), ACCT_PURSI_KEIKKA, F_DG + F_KURSSI, "Lento {aircraft}, {duration} min (kurssialennus 25%)"),
                FlightRule(Decimal('44'), ACCT_PURSI_KEIKKA, F_DG)
            ])
        ])),

        # Koululentomaksu
        FlightRule(lambda ev: Decimal('6'), ACCT_PURSI_INSTRUCTION, F_PURTSIKKA + [PurposeFilter("KOU")], "Koululentomaksu {aircraft}"),

        # Kalustomaksu
        CappedRule(ID_KALUSTOMAKSU_CAP_2024, Decimal('90'),
                   AllRules([FlightRule(Decimal('10'), ACCT_KALUSTO, F_PURTSIKKA,
                                    "Kalustomaksu {aircraft}, {duration} min"),
                            FlightRule(Decimal('10'), ACCT_KALUSTO, F_MOTTI,
                                    "Kalustomaksu {aircraft}, {duration} min")])),

        FlightRule(lambda ev: Decimal('2'), ACCT_LASKUTUSLISA, F_KAIKKI_KONEET + F_LASKUTUSLISA, "Laskutuslisä {aircraft}, {invoicing_comment}")
    ]
    
    return rules
