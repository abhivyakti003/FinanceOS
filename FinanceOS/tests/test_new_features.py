from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from app.services import (
    account_admin_service,
    account_service,
    auth_service,
    bill_service,
    credit_score_service,
    family_service,
    investment_service,
    notification_service,
    wealth_service,
)
from app.services import (
    transaction_service as ts,
)
from app.services.auth_service import AuthError

# ---- Investments -----------------------------------------------------------


def test_holdings_and_portfolio(user):
    investment_service.add_holding(user.id, "Parag Parikh Flexi Cap", "Mutual Fund", 100000, 125000)
    investment_service.add_holding(user.id, "EPF", "EPF", 300000, 300000)
    summary = investment_service.portfolio_summary(user.id)
    assert summary["current"] == Decimal("425000.00")
    assert summary["gain"] == Decimal("25000.00")
    assert list(investment_service.allocation(user.id))[0] == "EPF"
    assert wealth_service.net_worth(user.id)["investments"] == Decimal("425000.00")


def test_holding_validation_and_isolation(make_user):
    a, b = make_user(), make_user()
    with pytest.raises(investment_service.InvestmentError):
        investment_service.add_holding(a.id, "", "Stock", 1, 1)
    with pytest.raises(investment_service.InvestmentError):
        investment_service.add_holding(a.id, "X", "Stock", 0, 0)
    h = investment_service.add_holding(a.id, "TCS", "Stock", 1000, 1200, units=1)
    assert investment_service.delete_holding(b.id, h.id) is False
    with pytest.raises(investment_service.InvestmentError):
        investment_service.update_holding(b.id, h.id, current_value=1)


def test_cas_mapping_and_reimport_updates(user):
    cams = NS(
        folios=[
            NS(
                folio="123/45",
                schemes=[
                    NS(
                        scheme="Axis Bluechip Fund - Direct Growth",
                        isin="INF846K01DP8",
                        amfi="120465",
                        close=150.5,
                        valuation=NS(value=9000, cost=7500),
                    ),
                    NS(scheme="Closed scheme", isin="INF000", amfi=None, close=0, valuation=NS(value=0, cost=0)),
                ],
            )
        ],
        accounts=None,
        nps=None,
    )
    rows = investment_service.holdings_from_cas(cams)
    assert len(rows) == 1 and rows[0]["invested"] == Decimal("7500.00")
    assert investment_service.save_imported_holdings(user.id, rows) == {"added": 1, "updated": 0}
    rows[0]["current_value"] = Decimal("9500")
    assert investment_service.save_imported_holdings(user.id, rows) == {"added": 0, "updated": 1}
    assert investment_service.total_value(user.id) == Decimal("9500.00")

    nsdl = NS(
        folios=None,
        nps=[NS(pran="110012345678", value=50000)],
        accounts=[
            NS(
                client_id="1234",
                dp_id="IN30",
                equities=[NS(name="NIPPON INDIA ETF NIFTY BEES", isin="INF204KB14I2", num_shares=10, value=2700)],
                mutual_funds=[],
                bonds=[],
            )
        ],
    )
    rows = investment_service.holdings_from_cas(nsdl)
    assert {r["holding_type"] for r in rows} == {"ETF", "NPS"}


def test_cas_import_requires_password(user):
    with pytest.raises(investment_service.InvestmentError, match="password"):
        investment_service.import_cas(user.id, b"%PDF-1.4", "")


# ---- Bills -------------------------------------------------------------------


def test_shift_months_clamps_day():
    assert bill_service.shift_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert bill_service.shift_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_bill_lifecycle(user, bank):
    today = date.today()
    bill = bill_service.add_bill(user.id, "Electricity", 1800, today + timedelta(days=2), "Monthly")
    assert bill_service.bill_status(bill, today)["level"] == "soon"
    assert [b.id for b, _ in bill_service.due_soon(user.id, today)] == [bill.id]

    bill_service.mark_paid(user.id, bill.id, today, record_transaction=True, account_id=bank.id)
    updated = bill_service.list_bills(user.id)[0]
    assert updated.next_due_date == bill_service.shift_months(today + timedelta(days=2), 1)
    txn = ts.list_transactions(user.id)[0]
    assert txn.amount == Decimal("1800.00") and txn.category == "Bills & Utilities"


def test_overdue_bill_skips_to_future(user):
    today = date.today()
    bill = bill_service.add_bill(user.id, "Rent", 20000, today - timedelta(days=70), "Monthly", "Rent")
    assert bill_service.bill_status(bill, today)["level"] == "overdue"
    bill_service.mark_paid(user.id, bill.id, today)
    assert bill_service.list_bills(user.id)[0].next_due_date > today


def test_one_time_bill_deactivates(user):
    bill = bill_service.add_bill(user.id, "Car insurance", 9000, date.today() + timedelta(days=5), "Once", "Insurance")
    bill_service.mark_paid(user.id, bill.id)
    assert bill_service.list_bills(user.id) == []


def test_bill_validation(user):
    with pytest.raises(bill_service.BillError):
        bill_service.add_bill(user.id, "X", 0, date.today())
    with pytest.raises(bill_service.BillError):
        bill_service.add_bill(user.id, "X", 10, date.today(), "Weekly")


# ---- Family sharing ------------------------------------------------------------


def test_family_invite_accept_and_access(make_user):
    owner, member, stranger = make_user("mom@gmail.com"), make_user("son@gmail.com"), make_user()
    share = family_service.invite(owner.id, "SON@gmail.com", "Child")
    assert not family_service.can_view(member.id, owner.id)
    pending = family_service.incoming(member.id, "pending")
    assert pending[0]["owner_name"] == owner.name

    with pytest.raises(family_service.FamilyError):
        family_service.accept(stranger.id, share.id)
    family_service.accept(member.id, share.id)
    assert family_service.can_view(member.id, owner.id)
    assert not family_service.can_view(owner.id, member.id)  # one-way
    assert not family_service.can_view(stranger.id, owner.id)

    family_service.revoke(owner.id, share.id)
    assert not family_service.can_view(member.id, owner.id)


def test_family_invite_before_signup(make_user, outbox):
    owner = make_user("dad@gmail.com")
    share = family_service.invite(owner.id, "daughter@gmail.com")
    daughter = make_user("daughter@gmail.com")
    family_service.accept(daughter.id, share.id)
    assert family_service.can_view(daughter.id, owner.id)


def test_family_rules(make_user):
    owner = make_user("me@gmail.com")
    with pytest.raises(family_service.FamilyError):
        family_service.invite(owner.id, "me@gmail.com")
    family_service.invite(owner.id, "x@gmail.com")
    with pytest.raises(family_service.FamilyError):
        family_service.invite(owner.id, "x@gmail.com")


# ---- Credit score -------------------------------------------------------------


def test_credit_scores(user):
    with pytest.raises(credit_score_service.CreditScoreError):
        credit_score_service.add_score(user.id, 950, "CIBIL")
    credit_score_service.add_score(user.id, 720, "CIBIL", date.today() - timedelta(days=60))
    credit_score_service.add_score(user.id, 765, "CIBIL")
    hist = credit_score_service.history(user.id)
    assert [h.score for h in hist] == [720, 765]
    assert credit_score_service.band(765) == "Excellent"


# ---- Notifications ---------------------------------------------------------------


@pytest.fixture
def mailbox(monkeypatch):
    sent = []
    from app.services import email_service

    monkeypatch.setattr(
        email_service, "send_email", lambda to, subject, text, html=None: sent.append((to, subject, text))
    )
    return sent


def test_bill_reminder_sent_once(user, mailbox):
    today = date.today()
    bill_service.add_bill(user.id, "Netflix", 649, today + timedelta(days=1), "Monthly", "Entertainment")
    bill_service.add_bill(user.id, "Insurance", 9000, today + timedelta(days=20), "Yearly", "Insurance")
    assert notification_service.send_bill_reminders(today) == 1
    assert "Netflix" in mailbox[0][1]
    assert notification_service.send_bill_reminders(today) == 0  # not twice


def test_reminders_respect_preferences(user, mailbox):
    account_admin_service.set_preferences(user.id, email_reminders=False, weekly_summary=False)
    bill_service.add_bill(user.id, "Netflix", 649, date.today(), "Monthly", "Entertainment")
    assert notification_service.send_bill_reminders() == 0
    assert notification_service.send_weekly_summaries(force=True) == 0


def test_weekly_summary_mondays_only(user, bank, mailbox):
    monday = date(2026, 10, 19)
    ts.add_transaction(user.id, bank.id, monday - timedelta(days=2), 500, "debit", description="Swiggy")
    assert notification_service.send_weekly_summaries(monday + timedelta(days=1)) == 0
    assert notification_service.send_weekly_summaries(monday) == 1
    assert "Spent" in mailbox[0][2]
    assert notification_service.send_weekly_summaries(monday) == 0


def test_in_app_alerts(user, bank):
    bill_service.add_bill(user.id, "Rent", 20000, date.today() - timedelta(days=1), "Monthly", "Rent")
    alerts = notification_service.in_app_alerts(user.id)
    assert alerts and alerts[0]["level"] == "error"


# ---- Export and delete ------------------------------------------------------


def test_export_excel(user, bank):
    ts.add_transaction(user.id, bank.id, date.today(), 250, "debit", description="Zomato")
    data = account_admin_service.export_excel(user.id)
    import io

    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
    assert {"Profile", "Accounts", "Transactions", "Investments", "Bills"} <= set(sheets)
    assert len(sheets["Transactions"]) == 1


def test_delete_account_removes_everything(make_user):
    victim, other = make_user("gone@gmail.com"), make_user()
    acct = account_service.create_account(victim.id, "A", "Savings Account", 100)
    ts.add_transaction(victim.id, acct.id, date.today(), 10, "debit", description="tea")
    family_service.invite(other.id, "gone@gmail.com")
    with pytest.raises(AuthError):
        account_admin_service.delete_account(victim.id, "wrongpass1")
    account_admin_service.delete_account(victim.id, "Secret123")
    assert auth_service.get_user(victim.id) is None
    assert ts.list_transactions(victim.id) == []
    assert family_service.outgoing(other.id) == []
    with pytest.raises(AuthError):
        auth_service.authenticate("gone@gmail.com", "Secret123")
