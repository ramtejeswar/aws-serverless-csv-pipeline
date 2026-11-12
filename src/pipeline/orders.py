"""The orders CSV format: required columns and per-row validation.

Pure Python with no AWS calls, so it is the easiest part to test and to change.
To ingest a different kind of file, this is the only module to rewrite.
"""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from pipeline.errors import FileRejected

REQUIRED_COLUMNS = ("order_id", "customer_email", "amount", "currency", "order_date")
MAX_ROWS = 10_000
MAX_ERRORS_KEPT = 20  # the job keeps the first N row errors; the counts cover the rest
MAX_AMOUNT = Decimal("1000000000")

ORDER_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
AMOUNT = re.compile(r"^\d+(\.\d{1,2})?$")
CURRENCY = re.compile(r"^[A-Z]{3}$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class ParseResult:
    records: list = field(default_factory=list)  # valid rows, ready to store
    errors: list = field(default_factory=list)   # first MAX_ERRORS_KEPT of {"line", "error"}
    total_rows: int = 0
    error_count: int = 0


def validate_row(row):
    """Return a clean record, or raise ValueError saying what is wrong with the row."""
    value = {column: (row.get(column) or "").strip() for column in REQUIRED_COLUMNS}

    if not ORDER_ID.match(value["order_id"]):
        raise ValueError("order_id must be 1-64 letters, digits, '-' or '_'")
    if len(value["customer_email"]) > 254 or not EMAIL.match(value["customer_email"]):
        raise ValueError("customer_email is not a valid email address")
    if not AMOUNT.match(value["amount"]):
        raise ValueError("amount must be a positive number with at most 2 decimal places")
    amount = Decimal(value["amount"])  # Decimal, not float: money must not pick up rounding errors
    if amount <= 0 or amount > MAX_AMOUNT:
        raise ValueError("amount must be greater than 0 and at most 1,000,000,000")
    if not CURRENCY.match(value["currency"]):
        raise ValueError("currency must be a 3-letter uppercase code such as USD")
    if not ISO_DATE.match(value["order_date"]):
        raise ValueError("order_date must be a date in YYYY-MM-DD format")
    try:
        date.fromisoformat(value["order_date"])
    except ValueError:
        raise ValueError("order_date is not a real calendar date") from None

    return {
        "order_id": value["order_id"],
        "customer_email": value["customer_email"].lower(),
        "amount": amount,
        "currency": value["currency"],
        "order_date": value["order_date"],
    }


def parse(text):
    """Validate a whole CSV file. Bad rows are collected; a bad file raises FileRejected."""
    reader = csv.DictReader(io.StringIO(text))
    header = [(name or "").strip() for name in (reader.fieldnames or [])]
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise FileRejected(f"Missing required column(s): {', '.join(missing)}")
    reader.fieldnames = header

    result = ParseResult()
    seen = set()
    for row in reader:
        result.total_rows += 1
        if result.total_rows > MAX_ROWS:
            raise FileRejected(f"File has more than {MAX_ROWS} rows")
        try:
            record = validate_row(row)
            if record["order_id"] in seen:
                raise ValueError(f"duplicate order_id '{record['order_id']}'")
        except ValueError as err:
            result.error_count += 1
            if len(result.errors) < MAX_ERRORS_KEPT:
                result.errors.append({"line": reader.line_num, "error": str(err)})
            continue
        seen.add(record["order_id"])
        result.records.append(record)

    if result.total_rows == 0:
        raise FileRejected("File has a header but no data rows")
    return result
