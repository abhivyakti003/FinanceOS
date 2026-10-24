"""Turns raw bank narrations into merchant, payment mode and category.

Example:
    "UPI/DR/412345678901/SWIGGY/YESB/swiggy.stores@ybl/Food"
    -> mode="UPI", merchant="Swiggy", reference_id="412345678901", category="Food & Dining"

Order of decisions:
1. The user's own saved rule for this merchant (learned when they re-categorise).
2. Transfer detection (self transfers, credit card bill payments).
3. Built-in keyword list, matched on whole words so "ola" never matches "cola".
4. A default category.
"""

import re

EXPENSE_CATEGORIES = [
    "Food & Dining",
    "Groceries",
    "Shopping",
    "Travel",
    "Fuel",
    "Bills & Utilities",
    "Rent",
    "Entertainment",
    "Health",
    "Education",
    "EMI & Loans",
    "Insurance",
    "Investments",
    "Cash Withdrawal",
    "Personal Care",
    "Gifts & Donations",
    "Fees & Charges",
    "Other",
]
INCOME_CATEGORIES = [
    "Salary",
    "Business",
    "Freelance",
    "Interest",
    "Dividends",
    "Refund",
    "Cashback",
    "Other Income",
]
TRANSFER_CATEGORY = "Transfer"
ALL_CATEGORIES = EXPENSE_CATEGORIES + INCOME_CATEGORIES + [TRANSFER_CATEGORY]

# Money that leaves the account but isn't "spending".
NON_SPENDING_CATEGORIES = {"Investments", TRANSFER_CATEGORY}

DEBIT_KEYWORDS = {
    "Food & Dining": [
        "swiggy",
        "zomato",
        "dominos",
        "domino's",
        "mcdonalds",
        "mcdonald",
        "kfc",
        "pizza hut",
        "starbucks",
        "burger king",
        "subway",
        "haldiram",
        "chaayos",
        "cafe",
        "coffee",
        "restaurant",
        "eatclub",
        "box8",
        "faasos",
        "behrouz",
        "barbeque nation",
        "wow momo",
        "third wave",
        "blue tokai",
        "eatsure",
    ],
    "Groceries": [
        "bigbasket",
        "blinkit",
        "grofers",
        "zepto",
        "instamart",
        "dmart",
        "jiomart",
        "more retail",
        "reliance fresh",
        "nature's basket",
        "spencer",
        "milkbasket",
        "country delight",
        "supermarket",
        "kirana",
        "grocery",
    ],
    "Shopping": [
        "amazon",
        "flipkart",
        "myntra",
        "ajio",
        "nykaa",
        "meesho",
        "tata cliq",
        "croma",
        "reliance digital",
        "decathlon",
        "ikea",
        "lenskart",
        "firstcry",
        "pepperfry",
        "shoppers stop",
        "lifestyle",
        "westside",
        "h&m",
        "zara",
        "uniqlo",
        "snapdeal",
    ],
    "Travel": [
        "uber",
        "olacabs",
        "ola",
        "rapido",
        "irctc",
        "makemytrip",
        "goibibo",
        "cleartrip",
        "yatra",
        "ixigo",
        "redbus",
        "abhibus",
        "indigo",
        "air india",
        "akasa",
        "spicejet",
        "vistara",
        "metro",
        "bmtc",
        "fastag",
        "namma yatri",
        "blusmart",
        "airbnb",
        "oyo",
    ],
    "Fuel": [
        "hpcl",
        "bpcl",
        "iocl",
        "indian oil",
        "bharat petroleum",
        "hindustan petroleum",
        "shell",
        "nayara",
        "petrol",
        "fuel",
    ],
    "Bills & Utilities": [
        "bescom",
        "electricity",
        "tneb",
        "msedcl",
        "bses",
        "tata power",
        "adani electricity",
        "bwssb",
        "water bill",
        "airtel",
        "jio",
        "bsnl",
        "vodafone",
        "act fibernet",
        "hathway",
        "tata play",
        "dth",
        "recharge",
        "broadband",
        "piped gas",
        "indane",
        "bharat gas",
        "hp gas",
        "bbps",
        "billpay",
        "bill pay",
    ],
    "Rent": ["rent", "nobroker", "housing.com", "nestaway", "maintenance"],
    "Entertainment": [
        "netflix",
        "hotstar",
        "jiohotstar",
        "spotify",
        "prime video",
        "sonyliv",
        "zee5",
        "bookmyshow",
        "pvr",
        "inox",
        "youtube premium",
        "apple.com",
        "steam",
        "playstation",
        "district",
    ],
    "Health": [
        "apollo",
        "pharmeasy",
        "1mg",
        "netmeds",
        "medplus",
        "practo",
        "cult.fit",
        "cultfit",
        "hospital",
        "clinic",
        "pharmacy",
        "diagnostic",
        "lab",
        "healthians",
        "manipal",
        "fortis",
    ],
    "Education": [
        "byjus",
        "unacademy",
        "udemy",
        "coursera",
        "school",
        "college",
        "university",
        "tuition",
        "fees",
        "vedantu",
        "upgrad",
    ],
    "EMI & Loans": ["emi", "loan", "bajaj finance", "bajaj finserv", "home credit", "nach", "lazypay", "simpl"],
    "Insurance": ["lic", "insurance", "policybazaar", "acko", "hdfc life", "icici pru", "star health", "digit"],
    "Investments": [
        "zerodha",
        "groww",
        "upstox",
        "coin",
        "kuvera",
        "paytm money",
        "angel one",
        "mutual fund",
        "sip",
        "nps",
        "ppf",
        "smallcase",
        "indmoney",
        "etmoney",
        "iccl",
        "nsccl",
        "bse ltd",
        "cams",
        "kfintech",
    ],
    "Cash Withdrawal": ["atm", "cash withdrawal", "atw", "nwd", "cash wdl"],
    "Personal Care": ["salon", "urban company", "urbanclap", "spa", "barber", "gym"],
    "Gifts & Donations": ["donation", "charity", "temple", "giveindia", "ketto", "milaap"],
    "Fees & Charges": [
        "charges",
        "charge",
        "gst",
        "penalty",
        "late fee",
        "annual fee",
        "sms alert",
        "min bal",
        "processing fee",
        "chrg",
    ],
}

CREDIT_KEYWORDS = {
    "Salary": ["salary", "sal cr", "payroll", "sal for"],
    "Interest": ["interest", "int.pd", "int pd", "int.coll", "sb int", "fd int"],
    "Dividends": ["dividend", "div ", "ach cr"],
    "Refund": ["refund", "reversal", "rev ", "chargeback"],
    "Cashback": ["cashback", "cash back", "reward"],
    "Freelance": ["upwork", "fiverr", "freelance", "invoice"],
}

TRANSFER_KEYWORDS = [
    "self transfer",
    "own account",
    "to self",
    "from self",
    "cc payment",
    "credit card payment",
    "card payment",
    "cred club",
    "cred ",
    "cc bill",
    "creditcard",
    "sweep",
    "fd booking",
    "fd created",
    "rd installment",
]

MODE_PATTERNS = [
    ("UPI", r"\bupi\b"),
    ("NEFT", r"\bneft\b"),
    ("RTGS", r"\brtgs\b"),
    ("IMPS", r"\bimps\b|\bmmt\b"),
    ("ATM", r"\batm\b|\batw\b|\bnwd\b|cash wdl"),
    ("NACH", r"\bnach\b|\bach\b|\becs\b"),
    ("CARD", r"\bpos\b|\becom\b|\bvps\b|\bdebit card\b|\bcard\b"),
    ("CHEQUE", r"\bchq\b|\bcheque\b|\bclg\b|\bclearing\b"),
]

_STOPWORDS = {
    "upi",
    "dr",
    "cr",
    "p2a",
    "p2m",
    "payment",
    "payments",
    "pay",
    "paid",
    "to",
    "from",
    "ref",
    "neft",
    "imps",
    "rtgs",
    "pos",
    "ecom",
    "ach",
    "nach",
    "mmt",
    "txn",
    "transfer",
    "trf",
    "by",
    "the",
    "via",
    "for",
    "and",
    "sent",
    "using",
    "received",
    "collect",
    "request",
    "req",
    "bank",
    "ltd",
    "limited",
    "pvt",
    "private",
    "india",
    "yesb",
    "icic",
    "hdfc",
    "sbin",
    "utib",
    "kkbk",
    "pytm",
    "ybl",
    "okaxis",
    "okhdfcbank",
    "oksbi",
    "okicici",
    "paytm",
    "phonepe",
    "gpay",
    "bhim",
    "axl",
    "ibl",
    "apl",
    "idfc",
    "idfb",
    "punb",
    "barb",
    "cnrb",
    "ubin",
    "indb",
    "vps",
    "debit",
    "credit",
    "card",
    "atm",
    "chq",
    "inb",
    "net",
    "banking",
    "mb",
    "online",
    "no",
    "remarks",
    "note",
    "na",
    "nil",
    "cash",
    "wdl",
    "bil",
    "billpay",
}

_IFSC = re.compile(r"^[a-z]{4}0[a-z0-9]{6}$")


def _kw_pattern(keyword: str) -> re.Pattern:
    # Letters-only boundaries: "swiggy123" matches "swiggy", "cola" doesn't match "ola".
    return re.compile(r"(?<![a-z])" + re.escape(keyword) + r"(?![a-z])")


_DEBIT_PATTERNS = [(cat, _kw_pattern(k)) for cat, kws in DEBIT_KEYWORDS.items() for k in kws]
_CREDIT_PATTERNS = [(cat, _kw_pattern(k)) for cat, kws in CREDIT_KEYWORDS.items() for k in kws]
_TRANSFER_PATTERNS = [_kw_pattern(k.strip()) for k in TRANSFER_KEYWORDS]


def merchant_key(merchant: str | None) -> str | None:
    if not merchant:
        return None
    key = re.sub(r"[^a-z0-9]", "", merchant.lower())
    return key or None


def detect_mode(narration: str) -> str | None:
    text = (narration or "").lower()
    for mode, pattern in MODE_PATTERNS:
        if re.search(pattern, text):
            return mode
    return None


def _clean_token(token: str) -> str | None:
    token = token.strip(" .,_*#'\"()[]").lower()
    if len(token) < 3 or token in _STOPWORDS or _IFSC.match(token):
        return None
    digits = sum(ch.isdigit() for ch in token)
    if digits > len(token) / 3:
        return None
    return token


def extract_merchant(narration: str) -> str | None:
    text = (narration or "").lower()

    # Prefer the readable name segment; fall back to the UPI handle.
    parts = re.split(r"[/|\\:]+|\s-\s|-(?=[a-z])|(?<=[a-z0-9])-", text)
    for part in parts:
        if "@" in part:
            continue
        words = [_clean_token(w) for w in re.split(r"\s+", part.strip())]
        words = [w for w in words if w]
        if words:
            return " ".join(words[:3]).title()

    vpa = re.search(r"([a-z0-9._\-]+)@[a-z]+", text)
    if vpa:
        handle = re.split(r"[._\-]", vpa.group(1))[0]
        cleaned = _clean_token(handle)
        if cleaned:
            return cleaned.title()
    return None


def extract_reference(narration: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{12})(?!\d)", narration or "")  # UPI RRN is 12 digits
    if match:
        return match.group(1)
    match = re.search(r"\b([A-Z]{4}[A-Z0-9]{8,18})\b", narration or "")  # NEFT/IMPS UTR
    return match.group(1) if match else None


def parse_narration(narration: str) -> dict:
    return {
        "mode": detect_mode(narration),
        "merchant": extract_merchant(narration),
        "reference_id": extract_reference(narration),
    }


def is_transfer_narration(narration: str, txn_type: str, account_type: str | None = None) -> bool:
    text = (narration or "").lower()
    if any(p.search(text) for p in _TRANSFER_PATTERNS):
        return True
    # A payment received on a credit card is the user paying their own bill.
    if account_type == "Credit Card" and txn_type == "credit" and "payment" in text:
        return True
    return False


def suggest_category(
    narration: str,
    txn_type: str = "debit",
    merchant: str | None = None,
    user_rules: dict[str, str] | None = None,
    account_type: str | None = None,
) -> tuple[str, bool]:
    """Return (category, is_transfer)."""
    key = merchant_key(merchant)
    if user_rules and key and key in user_rules:
        category = user_rules[key]
        return category, category == TRANSFER_CATEGORY

    if is_transfer_narration(narration, txn_type, account_type):
        return TRANSFER_CATEGORY, True

    text = f"{narration or ''} {merchant or ''}".lower()
    patterns = _CREDIT_PATTERNS if txn_type == "credit" else _DEBIT_PATTERNS
    for category, pattern in patterns:
        if pattern.search(text):
            return category, False

    if txn_type == "credit":
        # Refunds from shopping merchants
        for category, pattern in _DEBIT_PATTERNS:
            if category in {"Shopping", "Food & Dining", "Travel"} and pattern.search(text):
                return "Refund", False
        return "Other Income", False
    return "Other", False
