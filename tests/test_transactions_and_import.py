from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import account_service, import_service
from app.services import transaction_service as ts
from app.services.account_service import AccountError
from app.services.transaction_service import TransactionError

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_add_transaction_autocategorises(user, bank):
    txn = ts.add_transaction(user.id, bank.id, date(2026, 7, 1), 450, "debit", description="Swiggy dinner")
    assert txn.category == "Food & Dining"
    assert txn.amount == Decimal("450.00")


def test_amount_validation(user, bank):
    for bad in (0, -5, "abc"):
        with pytest.raises(TransactionError):
            ts.add_transaction(user.id, bank.id, date(2026, 7, 1), bad, "debit")


def test_users_cannot_touch_each_others_data(make_user):
    alice, bob = make_user(), make_user()
    a_acct = account_service.create_account(alice.id, "A", "Savings Account", 0)
    txn = ts.add_transaction(alice.id, a_acct.id, date(2026, 7, 1), 100, "debit", description="tea")

    assert ts.delete_transaction(bob.id, txn.id) is False
    with pytest.raises(TransactionError):
        ts.update_transaction(bob.id, txn.id, amount=1)
    with pytest.raises(TransactionError):
        ts.add_transaction(bob.id, a_acct.id, date(2026, 7, 1), 50, "debit")
    with pytest.raises(AccountError):
        account_service.get_account(bob.id, a_acct.id)
    assert ts.list_transactions(bob.id) == []
    assert ts.get_transaction(alice.id, txn.id).amount == Decimal("100.00")


def test_balance_is_computed(user, bank):
    ts.add_transaction(user.id, bank.id, date(2026, 7, 1), 1000, "credit", description="gift")
    ts.add_transaction(user.id, bank.id, date(2026, 7, 2), 250.50, "debit", description="tea")
    assert account_service.account_balances(user.id)[bank.id] == Decimal("10749.50")
    account_service.set_current_balance(user.id, bank.id, 5000)
    assert account_service.account_balances(user.id)[bank.id] == Decimal("5000.00")


def test_credit_card_balance_is_negative(user):
    card = account_service.create_account(user.id, "Card", "Credit Card", 3000)
    assert account_service.account_balances(user.id)[card.id] == Decimal("-3000.00")


def test_recategorising_learns_merchant(user, bank):
    t1 = ts.add_transaction(
        user.id, bank.id, date(2026, 7, 1), 300, "debit", narration="UPI/DR/412345678901/SHARMA STORES/x@ybl"
    )
    t2 = ts.add_transaction(
        user.id, bank.id, date(2026, 7, 5), 200, "debit", narration="UPI/DR/412345678902/SHARMA STORES/x@ybl"
    )
    assert t1.category == "Other"
    ts.update_transaction(user.id, t1.id, category="Groceries")
    assert ts.get_transaction(user.id, t2.id).category == "Groceries"
    t3 = ts.add_transaction(
        user.id, bank.id, date(2026, 7, 9), 150, "debit", narration="UPI/DR/412345678903/SHARMA STORES/x@ybl"
    )
    assert t3.category == "Groceries"


def test_internal_transfer_detection(user, bank):
    savings2 = account_service.create_account(user.id, "SBI", "Savings Account", 0)
    ts.bulk_import(
        user.id,
        bank.id,
        [
            {
                "txn_date": date(2026, 7, 1),
                "amount": Decimal("20000"),
                "txn_type": "debit",
                "narration": "IMPS-P2A-MY SBI ACCOUNT",
            }
        ],
    )
    ts.bulk_import(
        user.id,
        savings2.id,
        [
            {
                "txn_date": date(2026, 7, 2),
                "amount": Decimal("20000"),
                "txn_type": "credit",
                "narration": "IMPS CR FROM HDFC",
            }
        ],
    )
    assert all(t.is_transfer for t in ts.list_transactions(user.id))


# ---- Statement import ------------------------------------------------------


def test_parse_hdfc_style_csv():
    parsed = import_service.parse_statement((SAMPLES / "hdfc_style_statement.csv").read_bytes(), "s.csv")
    assert len(parsed.rows) == 12
    first = parsed.rows[0]
    assert first["txn_date"] == date(2026, 7, 1)
    assert first["txn_type"] == "credit" and first["amount"] == Decimal("85000.00")
    # Wrapped line joined onto the previous transaction
    swiggy = [r for r in parsed.rows if "SWIGGY" in r["narration"]][0]
    assert "DINNER WITH FRIENDS" in swiggy["narration"]
    assert parsed.closing_balance == Decimal("94633.50")
    assert parsed.rows[1]["reference_id"] == "0000418412345601"


def test_parse_simple_signed_amounts():
    parsed = import_service.parse_statement((SAMPLES / "simple_statement.csv").read_bytes(), "s.csv")
    types = [r["txn_type"] for r in parsed.rows]
    assert types == ["credit", "debit", "debit", "debit"]


def test_parse_amount_column_with_drcr():
    grid = [
        ["Sl. No.", "Date", "Description", "Chq / Ref number", "Amount", "Dr / Cr", "Balance", "Dr / Cr"],
        ["1", "01-07-2026", "UPI/SWIGGY/412345678901", "", "450.00", "DR", "9,550.00", "CR"],
        ["2", "02-07-2026", "SALARY", "", "50,000.00", "CR", "59,550.00", "CR"],
    ]
    parsed = import_service.parse_grid(grid)
    assert [r["txn_type"] for r in parsed.rows] == ["debit", "credit"]


def test_excel_import_with_header_rows(tmp_path):
    import pandas as pd

    df = pd.DataFrame(
        [
            ["State Bank of India", None, None, None, None, None, None],
            [None] * 7,
            ["Txn Date", "Value Date", "Description", "Ref No./Cheque No.", "Debit", "Credit", "Balance"],
            ["1 Jul 2026", "1 Jul 2026", "BY TRANSFER-NEFT SALARY", "", "", "60,000.00", "70,000.00"],
            ["4 Jul 2026", "4 Jul 2026", "TO TRANSFER-UPI/DR/412345678901/BLINKIT", "", "820.00", "", "69,180.00"],
        ]
    )
    path = tmp_path / "sbi.xlsx"
    df.to_excel(path, header=False, index=False)
    parsed = import_service.parse_statement(path.read_bytes(), "sbi.xlsx")
    assert len(parsed.rows) == 2
    assert parsed.rows[1]["txn_type"] == "debit"
    assert parsed.closing_balance == Decimal("69180.00")


def test_import_dedupes_and_sets_balance(user, bank):
    data = (SAMPLES / "hdfc_style_statement.csv").read_bytes()
    parsed = import_service.parse_statement(data, "s.csv")
    first = import_service.import_statement(user.id, bank.id, parsed)
    assert first["inserted"] == 12 and first["skipped"] == 0
    assert first["balance_updated"]
    assert account_service.account_balances(user.id)[bank.id] == Decimal("94633.50")

    again = import_service.import_statement(user.id, bank.id, import_service.parse_statement(data, "s.csv"))
    assert again["inserted"] == 0 and again["skipped"] == 12

    cats = {t.narration[:12]: t.category for t in ts.list_transactions(user.id)}
    assert "Salary" in cats.values()
    assert "Investments" in cats.values()


def test_bad_files_give_clear_errors():
    with pytest.raises(import_service.StatementError):
        import_service.parse_statement(b"hello,world\n1,2\n", "x.csv")
    with pytest.raises(import_service.StatementError):
        import_service.parse_statement(b"data", "x.docx")
