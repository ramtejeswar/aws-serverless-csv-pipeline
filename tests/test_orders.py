"""CSV validation rules in pipeline/orders.py. No AWS involved."""
from decimal import Decimal

import pytest

from conftest import SAMPLE_CSV
from pipeline import orders
from pipeline.errors import FileRejected

HEADER = "order_id,customer_email,amount,currency,order_date\n"
GOOD_ROW = {
    "order_id": "ORD-1", "customer_email": "Asha@Example.com", "amount": "49.99",
    "currency": "USD", "order_date": "2026-11-01",
}


def test_valid_row_is_cleaned():
    assert orders.validate_row(GOOD_ROW) == {
        "order_id": "ORD-1", "customer_email": "asha@example.com", "amount": Decimal("49.99"),
        "currency": "USD", "order_date": "2026-11-01",
    }


@pytest.mark.parametrize("field,value", [
    ("order_id", ""), ("order_id", "has space"), ("order_id", "x" * 65),
    ("customer_email", "not-an-email"), ("customer_email", "a@b"), ("customer_email", ""),
    ("amount", "-5.00"), ("amount", "0"), ("amount", "abc"), ("amount", "1.999"),
    ("amount", "1e5"), ("amount", "NaN"), ("amount", "1000000000.01"), ("amount", ""),
    ("currency", "usd"), ("currency", "US"), ("currency", "DOLLARS"),
    ("order_date", "2026-13-40"), ("order_date", "11/01/2026"), ("order_date", "20261101"),
    ("order_date", "2026-02-30"),
])
def test_invalid_values_are_rejected(field, value):
    with pytest.raises(ValueError):
        orders.validate_row({**GOOD_ROW, field: value})


def test_sample_file_has_five_good_and_five_bad_rows():
    with open(SAMPLE_CSV, encoding="utf-8") as handle:
        result = orders.parse(handle.read())
    assert (result.total_rows, len(result.records), result.error_count) == (10, 5, 5)
    assert [r["order_id"] for r in result.records] == ["ORD-1001", "ORD-1002", "ORD-1003", "ORD-1006", "ORD-1010"]
    assert [e["line"] for e in result.errors] == [5, 6, 8, 9, 10]  # line 1 is the header


def test_duplicate_order_id_keeps_the_first():
    result = orders.parse(HEADER + "A1,a@x.io,1.00,USD,2026-01-01\nA1,b@x.io,2.00,USD,2026-01-02\n")
    assert len(result.records) == 1 and result.records[0]["customer_email"] == "a@x.io"
    assert "duplicate order_id" in result.errors[0]["error"]


def test_extra_columns_spaces_and_blank_lines_are_tolerated():
    text = " order_id , customer_email,amount,currency,order_date,notes\n\n A1 ,a@x.io, 5 ,USD,2026-01-01,hello\n"
    result = orders.parse(text)
    assert result.records[0]["order_id"] == "A1" and result.records[0]["amount"] == Decimal("5")


def test_short_row_is_a_row_error_not_a_crash():
    result = orders.parse(HEADER + "A1,a@x.io\n")
    assert result.error_count == 1 and result.records == []


def test_only_the_first_errors_are_kept_but_all_are_counted():
    result = orders.parse(HEADER + "bad row\n" * 50)
    assert result.error_count == 50
    assert len(result.errors) == orders.MAX_ERRORS_KEPT


@pytest.mark.parametrize("text,reason", [
    ("", "Missing required column"),
    ("order_id,amount\nA1,5\n", "customer_email, currency, order_date"),
    (HEADER, "no data rows"),
])
def test_unusable_files_are_rejected(text, reason):
    with pytest.raises(FileRejected, match=reason):
        orders.parse(text)


def test_too_many_rows_is_rejected(monkeypatch):
    monkeypatch.setattr(orders, "MAX_ROWS", 3)
    with pytest.raises(FileRejected, match="more than 3 rows"):
        orders.parse(HEADER + "A1,a@x.io,1,USD,2026-01-01\n" * 4)
