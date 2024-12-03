from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional, Dict
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class RecordType(Enum):
    HEADER = "00"
    TRANSACTION = "10"
    ADDITIONAL = "11"

@dataclass
class BankTransaction:
    # Required fields
    iban: str
    bic: str
    date: 'date'  # Type hint with string literal for forward reference
    name: str
    cents: int
    operation: str
    receipt_flag: str
    is_receipt: bool
    
    # Optional fields
    ledger_date: Optional['date'] = None
    value_date: Optional['date'] = None
    payment_date: Optional['date'] = None
    reference: Optional[str] = None
    message: Optional[str] = None
    our_reference: Optional[str] = None
    recipient_iban: Optional[str] = None
    recipient_bic: Optional[str] = None
    receipt_transactions: List['BankTransaction'] = field(default_factory=list)

    @property
    def amount_decimal(self) -> Decimal:
        return Decimal(str(self.cents)) / Decimal('100')

class NDAParsers:
    @staticmethod
    def parse_date(date_str: str) -> Optional[date]:
        """Parse date from YYMMDD format"""
        if date_str == "000000":
            return None
        return datetime.strptime(date_str, "%y%m%d").date()

    @staticmethod
    def parse_amount(sign: str, amount_str: str) -> int:
        """Parse amount in cents"""
        return int(sign + amount_str.lstrip('0'))

class NDAFileParser:
    def __init__(self):
        self._charset_mapping = {
            ord('['): 'Ä', ord('\\'): 'Ö', ord(']'): 'Å',
            ord('{'): 'ä', ord('|'): 'ö'
        }

    def _decode_text(self, text: str) -> str:
        """Handle special character encoding"""
        return text.translate(self._charset_mapping)

    def parse_file(self, file_lines: List[str]) -> List[BankTransaction]:
        """Main method to parse NDA file content"""
        transactions = []
        current_header = None
        current_transaction = None
        additional_info = []

        for line in file_lines:
            record_type = line[1:3]

            if record_type == RecordType.HEADER.value:
                current_header = self._parse_header(line)
            
            elif record_type == RecordType.TRANSACTION.value:
                if current_transaction:
                    transactions.append(self._create_transaction(
                        current_header, current_transaction, additional_info))
                current_transaction = self._parse_transaction_record(line)
                additional_info = []
            
            elif record_type == RecordType.ADDITIONAL.value:
                additional_info.append(self._parse_additional_record(line))

        # Handle last transaction
        if current_transaction:
            transactions.append(self._create_transaction(
                current_header, current_transaction, additional_info))

        return self._process_receipt_transactions(transactions)

    def _parse_header(self, line: str) -> Dict:
        """Parse header record (T00)"""
        parts = line[1+2+3+3+14+3+12+10+17+6+19+6+3+30+18+35+40+40+30:].strip().split()
        return {
            'iban': parts[0],
            'bic': parts[1]
        }

    def _parse_transaction_record(self, line: str) -> Dict:
        """Parse transaction record (T10)"""
        return {
            'ledger_date': NDAParsers.parse_date(line[30:36]),
            'value_date': NDAParsers.parse_date(line[42:48]),
            'payment_date': NDAParsers.parse_date(line[36:42]),
            'name': self._decode_text(line[108:143]).rstrip(),
            'cents': NDAParsers.parse_amount(line[87:88], line[88:106]),
            'operation': self._decode_text(line[52:87]).rstrip(),
            'reference': line[159:179].lstrip('0').strip() or None,
            'receipt_flag': line[106].strip(),
            'is_receipt': bool(line[187].strip())
        }

    def _parse_additional_record(self, line: str) -> Dict:
        """Parse additional information record (T11)"""
        subtype = line[6:8]
        data = {'subtype': subtype}

        if subtype == '06':
            data['reference'] = line[8:43].rstrip().lstrip('0')
        elif subtype == '00':
            data['message'] = self._decode_text(line[8:].rstrip())
        elif subtype == '11':
            data.update({
                'our_reference': self._decode_text(line[8:43].rstrip()),
                'recipient_iban': self._decode_text(line[43:78].rstrip()),
                'recipient_bic': self._decode_text(line[78:113].rstrip())
            })

        return data

    def _create_transaction(self, header: Dict, transaction: Dict, 
                       additional_info: List[Dict]) -> BankTransaction:
        """Create BankTransaction object from parsed data"""
        return BankTransaction(
            iban=header['iban'],
            bic=header['bic'],
            date=transaction['ledger_date'],  # Using ledger_date as the primary date
            ledger_date=transaction['ledger_date'],
            value_date=transaction['value_date'],
            payment_date=transaction['payment_date'],
            name=transaction['name'],
            cents=transaction['cents'],
            operation=transaction['operation'],
            reference=transaction['reference'],
            message=next((r['message'] for r in additional_info 
                        if r['subtype'] == '00'), None),
            our_reference=next((r['our_reference'] for r in additional_info 
                            if r['subtype'] == '11'), None),
            recipient_iban=next((r['recipient_iban'] for r in additional_info 
                            if r['subtype'] == '11'), None),
            recipient_bic=next((r['recipient_bic'] for r in additional_info 
                            if r['subtype'] == '11'), None),
            receipt_flag=transaction['receipt_flag'],
            is_receipt=transaction['is_receipt'],
            receipt_transactions=[]
        )

    def _process_receipt_transactions(self, transactions: List[BankTransaction]) -> List[BankTransaction]:
        """Process receipt relationships between transactions"""
        result = []
        current_main = None
        
        for txn in transactions:
            if not txn.receipt_flag and not txn.is_receipt:
                result.append(txn)
                current_main = None
            elif txn.receipt_flag == 'E':
                current_main = txn
                result.append(txn)
            elif current_main and txn.is_receipt:
                current_main.receipt_transactions.append(txn)
            else:
                logger.warning(f"Unexpected transaction pattern: {txn}")
                result.append(txn)

        return result