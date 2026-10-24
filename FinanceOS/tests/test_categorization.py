import pytest

from app.services import categorization_service as cat


@pytest.mark.parametrize(
    "narration,expected",
    [
        ("UPI/DR/412345678901/SWIGGY/YESB/swiggy.stores@ybl/Food", "Food & Dining"),
        ("UPI-ZOMATO LTD-ZOMATO@HDFCBANK-HDFC0000001-412345678901-ORDER", "Food & Dining"),
        ("POS 416021XXXXXX1234 DMART AVENUE SUPER", "Groceries"),
        ("UPI/DR/412345678901/OLA CABS/ICIC/olacabs@icici/Ride", "Travel"),
        ("ATM WDL/MG ROAD BANGALORE", "Cash Withdrawal"),
        ("ACH D- ZERODHA BROKING LTD", "Investments"),
        ("BIL/BPAY/BESCOM ELECTRICITY", "Bills & Utilities"),
    ],
)
def test_debit_categories(narration, expected):
    assert cat.suggest_category(narration, "debit", cat.extract_merchant(narration))[0] == expected


def test_word_boundaries_ola_is_not_cola():
    assert cat.suggest_category("UPI/DR/412345678901/COCA COLA STORE/pay", "debit")[0] != "Travel"
    assert cat.suggest_category("GRANOLA BAR CAFE", "debit")[0] != "Travel"


def test_credit_categories():
    assert cat.suggest_category("NEFT CR-ACME TECH-SALARY FOR SEP", "credit")[0] == "Salary"
    assert cat.suggest_category("CREDIT INTEREST INT.PD", "credit")[0] == "Interest"
    assert cat.suggest_category("REFUND AMAZON ORDER", "credit")[0] == "Refund"
    assert cat.suggest_category("UPI/CR/412345678901/RAHUL/", "credit")[0] == "Other Income"


def test_transfers_detected():
    assert cat.suggest_category("CRED CLUB CC PAYMENT", "debit") == ("Transfer", True)
    assert cat.suggest_category("PAYMENT RECEIVED THANK YOU", "credit", account_type="Credit Card") == (
        "Transfer",
        True,
    )


def test_user_rule_wins():
    rules = {"sharmastores": "Groceries"}
    assert cat.suggest_category("UPI/DR/1/SHARMA STORES/x", "debit", "Sharma Stores", rules)[0] == "Groceries"


def test_parse_upi_narration():
    parsed = cat.parse_narration("UPI/DR/412345678901/SWIGGY/YESB/swiggy.stores@ybl/Food")
    assert parsed["mode"] == "UPI"
    assert parsed["merchant"] == "Swiggy"
    assert parsed["reference_id"] == "412345678901"


def test_merchant_from_hdfc_style():
    assert cat.extract_merchant("UPI-ZOMATO LTD-ZOMATO@HDFCBANK-HDFC0000001-412345678901-ORDER") == "Zomato"
