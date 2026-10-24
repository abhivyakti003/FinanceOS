import pytest

from app.services import aa_service, account_service
from app.services import transaction_service as ts


def test_mock_aa_flow(user):
    consent = aa_service.start_link(user.id, "9876543210")
    first = aa_service.sync_consent(user.id, consent.id)
    assert first["status"] == "ACTIVE" and first["accounts"] == 1 and first["inserted"] > 50

    accounts = account_service.list_accounts(user.id)
    assert accounts[0].source == "aa"
    categories = {t.category for t in ts.list_transactions(user.id)}
    assert {"Salary", "Food & Dining", "Rent"} <= categories

    again = aa_service.sync_consent(user.id, consent.id)
    assert again["inserted"] == 0


def test_mobile_validation(user):
    with pytest.raises(aa_service.AAError):
        aa_service.start_link(user.id, "12345")
