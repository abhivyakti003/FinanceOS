"""Reads bank statements (CSV, Excel or PDF) from Indian banks.

Banks put logos, addresses and summaries above the actual table, and every
bank names its columns differently. So instead of expecting a fixed format,
this scans the first rows for something that looks like a header
("Date", "Narration", "Withdrawal Amt." ...) and maps the columns from there.

Tested layouts: HDFC, SBI, ICICI, Axis and Kotak style exports, plus a plain
Date / Description / Amount layout with negative numbers for debits.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd
from dateutil import parser as date_parser
from sqlalchemy import func, select

from app.database.db import get_session
from app.database.models import Transaction
from app.services.account_service import LIABILITY_ACCOUNT_TYPES, get_account, set_current_balance
from app.services.transaction_service import bulk_import


class StatementError(ValueError):
    pass


# Order matters: more specific names first.
COLUMN_SYNONYMS = {
    "date": [
        "txn date",
        "transaction date",
        "tran date",
        "trans date",
        "date",
        "posting date",
        "post date",
        "value date",
        "value dt",
    ],
    "narration": [
        "narration",
        "description",
        "particulars",
        "transaction details",
        "transaction remarks",
        "remarks",
        "details",
        "transaction description",
    ],
    "debit": [
        "withdrawal amt",
        "withdrawal amount",
        "withdrawal amount inr",
        "withdrawals",
        "withdrawal",
        "debit amount",
        "debit amt",
        "debits",
        "debit",
        "dr amount",
        "dr amt",
        "dr",
    ],
    "credit": [
        "deposit amt",
        "deposit amount",
        "deposit amount inr",
        "deposits",
        "deposit",
        "credit amount",
        "credit amt",
        "credits",
        "credit",
        "cr amount",
        "cr amt",
        "cr",
    ],
    "type": ["dr cr", "drcr", "cr dr", "debit credit", "txn type", "transaction type", "type"],
    "amount": ["transaction amount", "txn amount", "amount inr", "amount", "amt"],
    "balance": [
        "closing balance",
        "running balance",
        "available balance",
        "balance amt",
        "balance amount",
        "balance inr",
        "balance",
        "bal",
    ],
    "reference": [
        "chq ref no",
        "chqref no",
        "chq ref number",
        "ref no",
        "reference no",
        "ref number",
        "reference number",
        "cheque no",
        "chq no",
        "chqno",
        "utr",
        "reference",
    ],
}

DATE_FORMATS = [
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%d-%m-%y",
    "%d.%m.%Y",
    "%d.%m.%y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d %b %Y",
    "%d %b %y",
    "%d/%b/%Y",
    "%d/%b/%y",
    "%d-%B-%Y",
    "%d %B %Y",
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d",
    "%d/%m/%Y %H:%M:%S",
    "%d-%m-%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
]


@dataclass
class ParsedStatement:
    rows: list[dict] = field(default_factory=list)
    columns: dict[str, int] = field(default_factory=dict)
    header_row: int = -1
    closing_balance: Decimal | None = None
    start_date: date | None = None
    end_date: date | None = None
    skipped_lines: int = 0

    def preview(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "Date": r["txn_date"],
                    "Details": r["narration"],
                    "Debit": float(r["amount"]) if r["txn_type"] == "debit" else None,
                    "Credit": float(r["amount"]) if r["txn_type"] == "credit" else None,
                    "Balance": float(r["balance"]) if r.get("balance") is not None else None,
                }
                for r in self.rows
            ]
        )


# ---------------------------------------------------------------------------
# Low-level parsing
# ---------------------------------------------------------------------------


def _norm(cell) -> str:
    text = str(cell or "").lower().replace("\n", " ")
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return None
    text = re.sub(r"\s+", " ", text)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    if not re.search(r"\d", text) or len(text) > 25:
        return None
    try:
        return date_parser.parse(text, dayfirst=True, fuzzy=False).date()
    except (ValueError, OverflowError):
        return None


def parse_amount(value) -> tuple[Decimal | None, str | None]:
    """Returns (amount, hint) where hint is 'debit'/'credit' if the cell said so."""
    if value is None:
        return None, None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "-", "--", "0", "0.00", "0.0"}:
        return None, None
    hint = None
    lower = text.lower()
    if re.search(r"\bdr\.?$|\(dr\)$", lower):
        hint = "debit"
    elif re.search(r"\bcr\.?$|\(cr\)$", lower):
        hint = "credit"
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    cleaned = re.sub(r"[^0-9.]", "", text)
    if not cleaned or cleaned.count(".") > 1:
        return None, None
    try:
        amount = Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None, None
    if amount == 0:
        return None, None
    return (-amount if negative else amount), hint


def _match_columns(cells: list) -> dict[str, int]:
    normalized = [_norm(c) for c in cells]
    found: dict[str, int] = {}
    taken: set[int] = set()
    for role, names in COLUMN_SYNONYMS.items():
        best = None
        for name in names:
            for idx, cell in enumerate(normalized):
                if idx in taken or not cell:
                    continue
                if cell == name or (len(name) > 3 and cell.startswith(name)):
                    best = idx
                    break
            if best is not None:
                break
        if best is not None:
            found[role] = best
            taken.add(best)
    return found


def _find_header(grid: list[list]) -> tuple[int, dict[str, int]]:
    for i, row in enumerate(grid[:60]):
        cols = _match_columns(row)
        has_money = ("debit" in cols and "credit" in cols) or "amount" in cols
        if "date" in cols and "narration" in cols and has_money:
            return i, cols
    raise StatementError(
        "Couldn't find the transaction table. The statement needs columns for date, "
        "description and amount (or withdrawal and deposit)."
    )


# ---------------------------------------------------------------------------
# File readers -> grid of cells
# ---------------------------------------------------------------------------


def _read_csv(data: bytes) -> list[list]:
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise StatementError("Couldn't read this CSV file's text encoding.")
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _read_excel(data: bytes, filename: str) -> list[list]:
    engine = "xlrd" if filename.lower().endswith(".xls") else "openpyxl"
    try:
        frames = pd.read_excel(io.BytesIO(data), header=None, dtype=object, sheet_name=None, engine=engine)
    except ImportError as exc:
        raise StatementError("Reading old .xls files needs the 'xlrd' package. Run: pip install xlrd") from exc
    except Exception as exc:
        raise StatementError("Couldn't open this Excel file. It may be damaged or password protected.") from exc
    grid: list[list] = []
    for frame in frames.values():
        grid.extend(frame.where(pd.notna(frame), None).values.tolist())
    return grid


def _read_pdf(data: bytes, password: str | None) -> list[list]:
    import pdfplumber

    try:
        pdf = pdfplumber.open(io.BytesIO(data), password=password or "")
    except Exception as exc:
        name = type(exc).__name__.lower()
        if "password" in name or "encrypt" in str(exc).lower():
            raise StatementError(
                "This PDF is password protected. Enter the statement password "
                "(banks often use your date of birth or part of your name and account number)."
            ) from exc
        raise StatementError("Couldn't open this PDF.") from exc

    grid: list[list] = []
    with pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or page.extract_tables(
                {"vertical_strategy": "text", "horizontal_strategy": "text"}
            )
            for table in tables:
                grid.extend(table)
    if not grid:
        raise StatementError(
            "No table found in this PDF. If it's a scanned image, download the statement "
            "from net banking as CSV or Excel instead."
        )
    return grid


# ---------------------------------------------------------------------------
# Grid -> transactions
# ---------------------------------------------------------------------------


def parse_grid(grid: list[list]) -> ParsedStatement:
    grid = [list(r) for r in grid if r and any(c not in (None, "") for c in r)]
    header_idx, cols = _find_header(grid)
    result = ParsedStatement(columns=cols, header_row=header_idx)

    def cell(row, role):
        idx = cols.get(role)
        return row[idx] if idx is not None and idx < len(row) else None

    for raw in grid[header_idx + 1 :]:
        # Repeated header on later PDF pages
        if _match_columns(raw).get("date") == cols["date"] and _norm(cell(raw, "date")) in COLUMN_SYNONYMS["date"]:
            continue

        txn_date = parse_date(cell(raw, "date"))
        narration = re.sub(r"\s+", " ", str(cell(raw, "narration") or "")).strip()

        if txn_date is None:
            # A wrapped description line belongs to the previous transaction.
            if (
                narration
                and result.rows
                and parse_amount(cell(raw, "debit") if "debit" in cols else cell(raw, "amount"))[0] is None
            ):
                result.rows[-1]["narration"] = f"{result.rows[-1]['narration']} {narration}".strip()
            else:
                result.skipped_lines += 1
            continue

        txn_type = amount = None
        if "debit" in cols and "credit" in cols:
            debit, _ = parse_amount(cell(raw, "debit"))
            credit, _ = parse_amount(cell(raw, "credit"))
            if debit:
                txn_type, amount = "debit", abs(debit)
            elif credit:
                txn_type, amount = "credit", abs(credit)
        else:
            value, hint = parse_amount(cell(raw, "amount"))
            if value is not None:
                type_text = _norm(cell(raw, "type")) if "type" in cols else ""
                if type_text.startswith(("dr", "debit", "d ")) or type_text == "d":
                    txn_type = "debit"
                elif type_text.startswith(("cr", "credit", "c ")) or type_text == "c":
                    txn_type = "credit"
                else:
                    txn_type = hint or ("debit" if value < 0 else "credit")
                amount = abs(value)

        if not txn_type or not amount:
            result.skipped_lines += 1
            continue

        balance = None
        if "balance" in cols:
            bal, hint = parse_amount(cell(raw, "balance"))
            if bal is not None:
                balance = -abs(bal) if hint == "debit" else bal

        reference = str(cell(raw, "reference") or "").strip() or None
        if reference and set(reference) <= {"0"}:
            reference = None

        result.rows.append(
            {
                "txn_date": txn_date,
                "amount": amount,
                "txn_type": txn_type,
                "narration": narration,
                "reference_id": reference,
                "balance": balance,
            }
        )

    if not result.rows:
        raise StatementError("Found the table but no transactions in it.")

    dates = [r["txn_date"] for r in result.rows]
    result.start_date, result.end_date = min(dates), max(dates)
    latest = [r for r in result.rows if r["txn_date"] == result.end_date and r["balance"] is not None]
    if latest:
        # Statements can be newest-first or oldest-first; take the last row in
        # file order for the latest date if the file is ascending, else the first.
        ascending = result.rows[0]["txn_date"] <= result.rows[-1]["txn_date"]
        result.closing_balance = latest[-1]["balance"] if ascending else latest[0]["balance"]
    return result


def parse_statement(data: bytes, filename: str, password: str | None = None) -> ParsedStatement:
    if not data:
        raise StatementError("The file is empty.")
    if len(data) > 15 * 1024 * 1024:
        raise StatementError("The file is larger than 15 MB. Export a shorter date range.")
    name = filename.lower()
    if name.endswith(".csv") or name.endswith(".txt"):
        grid = _read_csv(data)
    elif name.endswith((".xlsx", ".xls")):
        grid = _read_excel(data, name)
    elif name.endswith(".pdf"):
        grid = _read_pdf(data, password)
    else:
        raise StatementError("Upload a CSV, Excel (.xlsx/.xls) or PDF statement.")
    return parse_grid(grid)


def import_statement(user_id: int, account_id: int, parsed: ParsedStatement, update_balance: bool = True) -> dict:
    """Save parsed rows to an account. Returns counts and whether the balance was updated."""
    account = get_account(user_id, account_id)  # also checks ownership
    balance_updated = False
    # One transaction: rows, transfer detection and balance update all save together.
    with get_session() as session:
        latest_before = session.scalar(
            select(func.max(Transaction.txn_date)).where(Transaction.account_id == account_id)
        )
        counts = bulk_import(user_id, account_id, parsed.rows, source="statement", session=session)
        trusted = latest_before is None or parsed.end_date >= latest_before
        if (
            update_balance
            and trusted
            and parsed.closing_balance is not None
            and account.account_type not in LIABILITY_ACCOUNT_TYPES
        ):
            set_current_balance(user_id, account_id, parsed.closing_balance, session=session)
            balance_updated = True
    return {**counts, "balance_updated": balance_updated}
