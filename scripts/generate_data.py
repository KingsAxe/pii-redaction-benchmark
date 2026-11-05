"""
generate_data.py – Generates 300 synthetic Nigerian business documents.

Rules enforced here:
- Faker used ONLY for dates, company names, and amounts.
- All name/address/phone data comes from nigerian_data.py static lists.
- Spans are recorded during string construction; .find() is never called.
- Files written with encoding="utf-8", newline="\n".
- Random seed = 42 everywhere.
- 300 docs: 100 health_report, 100 hr_intake, 100 vendor_invoice.
- 5 templates per doc type.
- Split: 100 dev (stratified), 200 test (stratified).
- ORDER_ID decoys: exactly 150 in total (50 per doc type), all 11 digits.
- Three ORDER_ID styles: mobile-like, 22-prefix, random.
- BVN and NIN entities have "cued": True/False.
- PHONE and PERSON entities have "format": <pattern string>.
- Each document dictionary has "length": character count of the document.
"""

import json
import os
import random
from pathlib import Path

from faker import Faker
from nigerian_data import (
    BVN_CUES,
    CITIES,
    FIRST_NAMES,
    INVOICE_PREFIX,
    MOBILE_PREFIXES,
    NIN_CUES,
    PHONE_FORMATS,
    STREET_NAMES,
    SURNAMES,
    TITLES,
)

# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
SEED = 42
random.seed(SEED)
fake = Faker("en_GB")          # Faker for dates/company/amounts only
Faker.seed(SEED)

# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Low-level span-tracked text builder
# ---------------------------------------------------------------------------

class DocBuilder:
    """Builds a document string and tracks spans incrementally without search."""

    def __init__(self):
        self._parts: list[str] = []
        self._cursor: int = 0
        self.entities: list[dict] = []
        self.decoys: list[dict] = []

    def raw(self, text: str) -> "DocBuilder":
        """Add plain text with no span tracking."""
        self._parts.append(text)
        self._cursor += len(text)
        return self

    def entity(self, text: str, entity_type: str, **extra) -> "DocBuilder":
        """Add entity text and track its span exactly."""
        start = self._cursor
        self._parts.append(text)
        self._cursor += len(text)
        record = {
            "type": entity_type,
            "start": start,
            "end": self._cursor,
            "text": text,
        }
        record.update(extra)
        self.entities.append(record)
        return self

    def decoy(self, text: str, decoy_type: str, **extra) -> "DocBuilder":
        """Add decoy text and track its span exactly."""
        start = self._cursor
        self._parts.append(text)
        self._cursor += len(text)
        record = {
            "type": decoy_type,
            "start": start,
            "end": self._cursor,
            "text": text,
        }
        record.update(extra)
        self.decoys.append(record)
        return self

    def build(self) -> str:
        return "".join(self._parts)


# ---------------------------------------------------------------------------
# Primitive generators (no Faker)
# ---------------------------------------------------------------------------

def gen_first() -> str:
    return random.choice(FIRST_NAMES)

def gen_last() -> str:
    return random.choice(SURNAMES)

def gen_title() -> str:
    return random.choice(TITLES)

PERSON_FORMAT_SPECS = [
    ("Title First Last", lambda f, l: f"{gen_title()} {f} {l}"),
    ("LAST, First", lambda f, l: f"{l.upper()}, {f}"),
    ("First Last", lambda f, l: f"{f} {l}"),
    ("F. Last", lambda f, l: f"{f[0]}. {l}"),
    ("Last, First F.", lambda f, l: f"{l}, {f} {f[0]}."),
]

def gen_person() -> tuple[str, str]:
    """Return (formatted_name_str, format_label)."""
    first = gen_first()
    last = gen_last()
    fmt_label, fn = random.choice(PERSON_FORMAT_SPECS)
    return fn(first, last), fmt_label

PHONE_FORMAT_SPECS = [
    ("+234 XXX XXX XXXX", lambda a, b, c: f"+234 {a} {b} {c}"),
    ("0XXXXXXXXXX", lambda a, b, c: f"0{a}{b}{c}"),
    ("+234-XXX-XXX-XXXX", lambda a, b, c: f"+234-{a}-{b}-{c}"),
]

def gen_phone() -> tuple[str, str]:
    """Return (formatted_phone_str, format_label)."""
    prefix = random.choice(MOBILE_PREFIXES)
    mid = f"{random.randint(0, 999):03d}"
    end = f"{random.randint(0, 9999):04d}"
    fmt_label, fn = random.choice(PHONE_FORMAT_SPECS)
    return fn(prefix, mid, end), fmt_label

def gen_email(first: str, last: str) -> str:
    domains = [
        "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
        "nigeriamail.ng", "corpmail.ng", "healthng.gov.ng",
    ]
    sep = random.choice([".", "_", ""])
    local = f"{first.lower()}{sep}{last.lower()}".replace(" ", "").replace("'", "")
    return f"{local}@{random.choice(domains)}"

def gen_address() -> str:
    num = random.randint(1, 150)
    street = random.choice(STREET_NAMES)
    city = random.choice(list(CITIES.keys()))
    area = random.choice(CITIES[city])
    return f"{num} {street}, {area}, {city}"

def gen_11digit() -> str:
    return f"{random.randint(10_000_000_000, 99_999_999_999)}"

# Non-cue prefixes for bare BVN/NIN
NON_ID_CUES = ["ID:", "ID No:", "Identifier:", "National Identifier:", "Record No:", "Ref No:"]

def write_bvn(b: DocBuilder, pii_set: set, cued: bool) -> None:
    """Write an 11-digit BVN entity with explicit 'cued' boolean."""
    val = gen_11digit()
    pii_set.add(val)
    if cued:
        cue = random.choice(BVN_CUES)
        b.raw(f"{cue} ").entity(val, "BVN", cued=True).raw("\n")
    else:
        prefix = random.choice(NON_ID_CUES)
        b.raw(f"{prefix} ").entity(val, "BVN", cued=False).raw("\n")

def write_nin(b: DocBuilder, pii_set: set, cued: bool) -> None:
    """Write an 11-digit NIN entity with explicit 'cued' boolean."""
    val = gen_11digit()
    pii_set.add(val)
    if cued:
        cue = random.choice(NIN_CUES)
        b.raw(f"{cue} ").entity(val, "NIN", cued=True).raw("\n")
    else:
        prefix = random.choice(NON_ID_CUES)
        b.raw(f"{prefix} ").entity(val, "NIN", cued=False).raw("\n")

# Faker-only helpers
def gen_date() -> str:
    return fake.date_between(start_date="-5y", end_date="today").strftime("%d %B %Y")

def gen_company() -> str:
    return fake.company().replace(",", "")

def gen_amount() -> str:
    return f"NGN {random.randint(10_000, 10_000_000):,}.00"

def gen_invoice_number() -> str:
    prefix = random.choice(INVOICE_PREFIX)
    num = random.randint(10000, 999999)
    return f"{prefix}-{num}"

def gen_po_number() -> str:
    return f"PO-{random.randint(100000, 999999)}"

# ORDER_ID generator
ORDER_ID_CUES = ["Order Ref:", "Tracking No.", "Order ID:"]
ORDER_ID_BARE_PREFIXES = ["Ref:", "Item No:", "Lot:", "Batch:", ""]

MOBILE_LIKE_PREFIXES = [
    "0803", "0705", "0810", "0806", "0703", "0813",
    "0814", "0816", "0903", "0906", "0802", "0805",
]

def gen_order_id_value(style: str, pii_set: set) -> str:
    """Generate an 11-digit ORDER_ID string of the given style not colliding with any PII."""
    while True:
        if style == "mobile":
            pfx = random.choice(MOBILE_LIKE_PREFIXES)
            rem = f"{random.randint(0, 9_999_999):07d}"
            val = f"{pfx}{rem}"
        elif style == "22":
            rem = f"{random.randint(0, 999_999_999):09d}"
            val = f"22{rem}"
        else:
            val = f"{random.randint(10_000_000_000, 99_999_999_999)}"
        if val not in pii_set:
            return val

def _write_order_id(b: DocBuilder, order_id_spec: dict | None,
                    default_bare_prefix: str = "Ref:") -> None:
    """Inject an ORDER_ID decoy if order_id_spec is provided."""
    if not order_id_spec:
        return
    val = order_id_spec["value"]
    if order_id_spec["cued"]:
        cue = order_id_spec["cue"]
        b.raw(f"{cue} ").decoy(val, "ORDER_ID", cued=True, style=order_id_spec["style"]).raw("\n")
    else:
        prefix = order_id_spec.get("bare_prefix", default_bare_prefix)
        if prefix:
            b.raw(f"{prefix} ").decoy(val, "ORDER_ID", cued=False, style=order_id_spec["style"]).raw("\n")
        else:
            b.decoy(val, "ORDER_ID", cued=False, style=order_id_spec["style"]).raw("\n")


# ---------------------------------------------------------------------------
# Document Templates
# ---------------------------------------------------------------------------

# ---- Health Report Templates -----------------------------------------------

def health_report_t1(b: DocBuilder, pii_set: set, order_id_spec: dict | None) -> DocBuilder:
    """Community Health Field Report – narrative style."""
    first, last = gen_first(), gen_last()
    name_text, name_fmt = gen_person()
    phone_text, phone_fmt = gen_phone()
    email = gen_email(first, last)
    address = gen_address()
    date = gen_date()
    facility = gen_company() + " Clinic"
    ref = gen_invoice_number()

    pii_set.update([name_text, phone_text, email, address])

    b.raw("COMMUNITY HEALTH FIELD REPORT\n")
    b.raw(f"Facility: {facility}\n")
    b.raw("Report Ref: ").decoy(ref, "INVOICE_NUMBER").raw("\n")
    b.raw(f"Date: {date}\n\n")
    b.raw("Patient Name: ").entity(name_text, "PERSON", format=name_fmt).raw("\n")
    b.raw("Contact: ").entity(phone_text, "PHONE", format=phone_fmt).raw("\n")
    b.raw("Email: ").entity(email, "EMAIL").raw("\n")
    b.raw("Residential Address: ").entity(address, "ADDRESS").raw("\n")
    write_bvn(b, pii_set, cued=random.random() < 0.60)
    _write_order_id(b, order_id_spec, default_bare_prefix="Lab Ref:")
    b.raw("\nClinical Notes: Patient presented with complaints of persistent fever. ")
    b.raw(f"Referred to secondary care on {date}.\n")
    of2_text, of2_fmt = gen_person()
    pii_set.add(of2_text)
    b.raw("Case Officer: ").entity(of2_text, "PERSON", format=of2_fmt).raw("\n")
    return b


def health_report_t2(b: DocBuilder, pii_set: set, order_id_spec: dict | None) -> DocBuilder:
    """Vaccination Outreach Record."""
    name_text, name_fmt = gen_person()
    phone_text, phone_fmt = gen_phone()
    address = gen_address()
    date = gen_date()
    batch = gen_invoice_number()

    pii_set.update([name_text, phone_text, address])

    b.raw("VACCINATION OUTREACH RECORD\n")
    b.raw(f"Campaign Date: {date}\n")
    b.raw("Batch Ref: ").decoy(batch, "INVOICE_NUMBER").raw("\n\n")
    b.raw("Beneficiary: ").entity(name_text, "PERSON", format=name_fmt).raw("\n")
    b.raw("Mobile: ").entity(phone_text, "PHONE", format=phone_fmt).raw("\n")
    b.raw("Address: ").entity(address, "ADDRESS").raw("\n")
    write_nin(b, pii_set, cued=random.random() < 0.60)
    b.raw("\nVaccine administered: Meningococcal A.\n")
    _write_order_id(b, order_id_spec, default_bare_prefix="Lot No:")
    of2_text, of2_fmt = gen_person()
    pii_set.add(of2_text)
    b.raw("Administered by: ").entity(of2_text, "PERSON", format=of2_fmt).raw("\n")
    return b


def health_report_t3(b: DocBuilder, pii_set: set, order_id_spec: dict | None) -> DocBuilder:
    """Maternal Health Assessment."""
    first, last = gen_first(), gen_last()
    name_text, name_fmt = gen_person()
    phone_text, phone_fmt = gen_phone()
    email = gen_email(first, last)
    address = gen_address()
    date = gen_date()

    pii_set.update([name_text, phone_text, email, address])

    b.raw("MATERNAL HEALTH ASSESSMENT FORM\n")
    b.raw(f"Assessment Date: {date}\n\n")
    b.raw("Mother's Name: ").entity(name_text, "PERSON", format=name_fmt).raw("\n")
    b.raw("Phone: ").entity(phone_text, "PHONE", format=phone_fmt).raw("\n")
    b.raw("Email: ").entity(email, "EMAIL").raw("\n")
    b.raw("Home Address: ").entity(address, "ADDRESS").raw("\n")
    write_bvn(b, pii_set, cued=random.random() < 0.60)
    write_nin(b, pii_set, cued=random.random() < 0.60)
    _write_order_id(b, order_id_spec, default_bare_prefix="Record No:")
    b.raw(f"\nObstetric History: G2P1. Last delivery: {date}.\n")
    of2_text, of2_fmt = gen_person()
    pii_set.add(of2_text)
    b.raw("Attending Midwife: ").entity(of2_text, "PERSON", format=of2_fmt).raw("\n")
    return b


def health_report_t4(b: DocBuilder, pii_set: set, order_id_spec: dict | None) -> DocBuilder:
    """HIV Counselling Session Note."""
    name_text, name_fmt = gen_person()
    phone_text, phone_fmt = gen_phone()
    address = gen_address()
    date = gen_date()
    ref = gen_po_number()

    pii_set.update([name_text, phone_text, address])

    b.raw("HIV COUNSELLING SESSION NOTE\n")
    b.raw(f"Session Date: {date}\n")
    b.raw("Referral ID: ").decoy(ref, "PO_NUMBER").raw("\n\n")
    b.raw("Client: ").entity(name_text, "PERSON", format=name_fmt).raw("\n")
    b.raw("Phone: ").entity(phone_text, "PHONE", format=phone_fmt).raw("\n")
    b.raw("Residence: ").entity(address, "ADDRESS").raw("\n")
    write_nin(b, pii_set, cued=random.random() < 0.60)
    _write_order_id(b, order_id_spec, default_bare_prefix="Session Ref:")
    b.raw("\nCounsellor Notes: Client tested positive. Linked to ART site.\n")
    of2_text, of2_fmt = gen_person()
    pii_set.add(of2_text)
    b.raw("Counsellor: ").entity(of2_text, "PERSON", format=of2_fmt).raw("\n")
    return b


def health_report_t5(b: DocBuilder, pii_set: set, order_id_spec: dict | None) -> DocBuilder:
    """Mental Health Referral Letter."""
    first, last = gen_first(), gen_last()
    name_text, name_fmt = gen_person()
    phone_text, phone_fmt = gen_phone()
    email = gen_email(first, last)
    address = gen_address()
    date = gen_date()
    facility = gen_company() + " Hospital"

    pii_set.update([name_text, phone_text, email, address])

    b.raw("MENTAL HEALTH REFERRAL LETTER\n")
    b.raw(f"Date: {date}\nReferring Facility: {facility}\n\n")
    b.raw("Patient: ").entity(name_text, "PERSON", format=name_fmt).raw("\n")
    b.raw("Phone: ").entity(phone_text, "PHONE", format=phone_fmt).raw("\n")
    b.raw("Email: ").entity(email, "EMAIL").raw("\n")
    b.raw("Address: ").entity(address, "ADDRESS").raw("\n")
    write_bvn(b, pii_set, cued=random.random() < 0.60)
    _write_order_id(b, order_id_spec, default_bare_prefix="Referral Code:")
    b.raw("\nReason for referral: Acute anxiety disorder, recommended CBT.\n")
    of2_text, of2_fmt = gen_person()
    pii_set.add(of2_text)
    b.raw("Referred by: ").entity(of2_text, "PERSON", format=of2_fmt).raw("\n")
    return b


# ---- HR Intake Templates ----------------------------------------------------

def hr_intake_t1(b: DocBuilder, pii_set: set, order_id_spec: dict | None) -> DocBuilder:
    """Standard Employee Onboarding Form."""
    first, last = gen_first(), gen_last()
    name_text, name_fmt = gen_person()
    phone_text, phone_fmt = gen_phone()
    email = gen_email(first, last)
    address = gen_address()
    date = gen_date()
    emp_id = gen_invoice_number()

    pii_set.update([name_text, phone_text, email, address])

    b.raw("EMPLOYEE ONBOARDING FORM\n")
    b.raw(f"Date: {date}\n")
    b.raw("Employee ID: ").decoy(emp_id, "INVOICE_NUMBER").raw("\n\n")
    b.raw("Full Name: ").entity(name_text, "PERSON", format=name_fmt).raw("\n")
    b.raw("Phone: ").entity(phone_text, "PHONE", format=phone_fmt).raw("\n")
    b.raw("Email: ").entity(email, "EMAIL").raw("\n")
    b.raw("Home Address: ").entity(address, "ADDRESS").raw("\n")
    write_bvn(b, pii_set, cued=random.random() < 0.60)
    write_nin(b, pii_set, cued=random.random() < 0.60)
    _write_order_id(b, order_id_spec, default_bare_prefix="File No:")
    b.raw(f"\nDepartment: Finance\nPosition: Senior Analyst\nStart Date: {date}\n")
    of2_text, of2_fmt = gen_person()
    pii_set.add(of2_text)
    b.raw("HR Officer: ").entity(of2_text, "PERSON", format=of2_fmt).raw("\n")
    return b


def hr_intake_t2(b: DocBuilder, pii_set: set, order_id_spec: dict | None) -> DocBuilder:
    """Job Application Form."""
    first, last = gen_first(), gen_last()
    name_text, name_fmt = gen_person()
    phone_text, phone_fmt = gen_phone()
    email = gen_email(first, last)
    address = gen_address()
    date = gen_date()
    ref = gen_po_number()

    pii_set.update([name_text, phone_text, email, address])

    b.raw("JOB APPLICATION FORM\n")
    b.raw(f"Application Date: {date}\n")
    b.raw("Application Ref: ").decoy(ref, "PO_NUMBER").raw("\n\n")
    b.raw("Applicant Name: ").entity(name_text, "PERSON", format=name_fmt).raw("\n")
    b.raw("Mobile: ").entity(phone_text, "PHONE", format=phone_fmt).raw("\n")
    b.raw("Email Address: ").entity(email, "EMAIL").raw("\n")
    b.raw("Current Address: ").entity(address, "ADDRESS").raw("\n")
    write_nin(b, pii_set, cued=random.random() < 0.60)
    _write_order_id(b, order_id_spec, default_bare_prefix="Application Code:")
    b.raw("\nPosition Applied For: Operations Manager\n")
    ref2_text, ref2_fmt = gen_person()
    p2_text, p2_fmt = gen_phone()
    pii_set.update([ref2_text, p2_text])
    b.raw("Referee: ").entity(ref2_text, "PERSON", format=ref2_fmt).raw("\n")
    b.raw("Referee Phone: ").entity(p2_text, "PHONE", format=p2_fmt).raw("\n")
    return b


def hr_intake_t3(b: DocBuilder, pii_set: set, order_id_spec: dict | None) -> DocBuilder:
    """Staff Medical Benefit Registration."""
    first, last = gen_first(), gen_last()
    name_text, name_fmt = gen_person()
    phone_text, phone_fmt = gen_phone()
    email = gen_email(first, last)
    address = gen_address()
    date = gen_date()
    pol = gen_invoice_number()

    pii_set.update([name_text, phone_text, email, address])

    b.raw("STAFF MEDICAL BENEFIT REGISTRATION\n")
    b.raw(f"Date: {date}\n")
    b.raw("Policy Ref: ").decoy(pol, "INVOICE_NUMBER").raw("\n\n")
    b.raw("Employee: ").entity(name_text, "PERSON", format=name_fmt).raw("\n")
    b.raw("Phone: ").entity(phone_text, "PHONE", format=phone_fmt).raw("\n")
    b.raw("Email: ").entity(email, "EMAIL").raw("\n")
    b.raw("Address: ").entity(address, "ADDRESS").raw("\n")
    write_bvn(b, pii_set, cued=random.random() < 0.60)
    _write_order_id(b, order_id_spec, default_bare_prefix="Benefit Ref:")
    b.raw("\nPlan: Family HMO Gold\nDependants: ")
    dep_text, dep_fmt = gen_person()
    pii_set.add(dep_text)
    b.entity(dep_text, "PERSON", format=dep_fmt).raw("\n")
    hr_text, hr_fmt = gen_person()
    pii_set.add(hr_text)
    b.raw("Registering HR: ").entity(hr_text, "PERSON", format=hr_fmt).raw("\n")
    return b


def hr_intake_t4(b: DocBuilder, pii_set: set, order_id_spec: dict | None) -> DocBuilder:
    """Disciplinary Hearing Notice."""
    name_text, name_fmt = gen_person()
    phone_text, phone_fmt = gen_phone()
    address = gen_address()
    date = gen_date()
    case_ref = gen_invoice_number()

    pii_set.update([name_text, phone_text, address])

    b.raw("DISCIPLINARY HEARING NOTICE\n")
    b.raw(f"Issued: {date}\n")
    b.raw("Case Ref: ").decoy(case_ref, "INVOICE_NUMBER").raw("\n\n")
    b.raw("Employee: ").entity(name_text, "PERSON", format=name_fmt).raw("\n")
    b.raw("Contact: ").entity(phone_text, "PHONE", format=phone_fmt).raw("\n")
    b.raw("Address: ").entity(address, "ADDRESS").raw("\n")
    write_nin(b, pii_set, cued=random.random() < 0.60)
    _write_order_id(b, order_id_spec, default_bare_prefix="Case Code:")
    b.raw("\nAllegation: Unauthorised absence exceeding 5 days.\n")
    h_text, h_fmt = gen_person()
    w_text, w_fmt = gen_person()
    pii_set.update([h_text, w_text])
    b.raw("Hearing Officer: ").entity(h_text, "PERSON", format=h_fmt).raw("\n")
    b.raw("Witness: ").entity(w_text, "PERSON", format=w_fmt).raw("\n")
    return b


def hr_intake_t5(b: DocBuilder, pii_set: set, order_id_spec: dict | None) -> DocBuilder:
    """Pension Enrolment Form."""
    first, last = gen_first(), gen_last()
    name_text, name_fmt = gen_person()
    phone_text, phone_fmt = gen_phone()
    email = gen_email(first, last)
    address = gen_address()
    date = gen_date()
    contrib = gen_amount()
    plan_ref = gen_invoice_number()

    pii_set.update([name_text, phone_text, email, address])

    b.raw("PENSION ENROLMENT FORM\n")
    b.raw(f"Date: {date}\n")
    b.raw("Plan Ref: ").decoy(plan_ref, "INVOICE_NUMBER").raw("\n\n")
    b.raw("Employee Name: ").entity(name_text, "PERSON", format=name_fmt).raw("\n")
    b.raw("Phone: ").entity(phone_text, "PHONE", format=phone_fmt).raw("\n")
    b.raw("Email: ").entity(email, "EMAIL").raw("\n")
    b.raw("Address: ").entity(address, "ADDRESS").raw("\n")
    write_bvn(b, pii_set, cued=random.random() < 0.60)
    write_nin(b, pii_set, cued=random.random() < 0.60)
    _write_order_id(b, order_id_spec, default_bare_prefix="Enrolment Ref:")
    b.raw("\nMonthly Contribution: ").decoy(contrib, "AMOUNT").raw("\n")
    ben_text, ben_fmt = gen_person()
    pii_set.add(ben_text)
    b.raw("Nominated Beneficiary: ").entity(ben_text, "PERSON", format=ben_fmt).raw("\n")
    return b


# ---- Vendor Invoice Templates -----------------------------------------------

def vendor_invoice_t1(b: DocBuilder, pii_set: set, order_id_spec: dict | None) -> DocBuilder:
    """Standard Vendor Tax Invoice."""
    first, last = gen_first(), gen_last()
    name_text, name_fmt = gen_person()
    phone_text, phone_fmt = gen_phone()
    email = gen_email(first, last)
    address = gen_address()
    date = gen_date()
    inv = gen_invoice_number()
    po = gen_po_number()
    amount = gen_amount()
    company = gen_company()

    pii_set.update([name_text, phone_text, email, address])

    b.raw(f"TAX INVOICE\n{company}\n")
    b.raw("Invoice No: ").decoy(inv, "INVOICE_NUMBER").raw("\n")
    b.raw("PO No: ").decoy(po, "PO_NUMBER").raw("\n")
    b.raw(f"Date: {date}\n\n")
    b.raw("Billed To: ").entity(name_text, "PERSON", format=name_fmt).raw("\n")
    b.raw("Phone: ").entity(phone_text, "PHONE", format=phone_fmt).raw("\n")
    b.raw("Email: ").entity(email, "EMAIL").raw("\n")
    b.raw("Address: ").entity(address, "ADDRESS").raw("\n")
    write_bvn(b, pii_set, cued=random.random() < 0.60)
    _write_order_id(b, order_id_spec, default_bare_prefix="Invoice Code:")
    b.raw("\nDescription: IT Equipment Supply\n")
    b.raw("Amount: ").decoy(amount, "AMOUNT").raw("\n")
    auth_text, auth_fmt = gen_person()
    pii_set.add(auth_text)
    b.raw("Authorised by: ").entity(auth_text, "PERSON", format=auth_fmt).raw("\n")
    return b


def vendor_invoice_t2(b: DocBuilder, pii_set: set, order_id_spec: dict | None) -> DocBuilder:
    """Local Purchase Order (LPO)."""
    name_text, name_fmt = gen_person()
    phone_text, phone_fmt = gen_phone()
    address = gen_address()
    date = gen_date()
    lpo = gen_invoice_number()
    amount = gen_amount()

    pii_set.update([name_text, phone_text, address])

    b.raw("LOCAL PURCHASE ORDER\n")
    b.raw("LPO No: ").decoy(lpo, "INVOICE_NUMBER").raw("\n")
    _write_order_id(b, order_id_spec, default_bare_prefix="Order Code:")
    b.raw(f"Date: {date}\n\n")
    b.raw("Vendor Contact: ").entity(name_text, "PERSON", format=name_fmt).raw("\n")
    b.raw("Phone: ").entity(phone_text, "PHONE", format=phone_fmt).raw("\n")
    b.raw("Delivery Address: ").entity(address, "ADDRESS").raw("\n")
    write_nin(b, pii_set, cued=random.random() < 0.60)
    b.raw("\nItem: Office Furniture (10 units)\n")
    b.raw("Total Value: ").decoy(amount, "AMOUNT").raw("\n")
    proc_text, proc_fmt = gen_person()
    pii_set.add(proc_text)
    b.raw("Procurement Officer: ").entity(proc_text, "PERSON", format=proc_fmt).raw("\n")
    return b


def vendor_invoice_t3(b: DocBuilder, pii_set: set, order_id_spec: dict | None) -> DocBuilder:
    """Service Contract Invoice."""
    first, last = gen_first(), gen_last()
    name_text, name_fmt = gen_person()
    phone_text, phone_fmt = gen_phone()
    email = gen_email(first, last)
    address = gen_address()
    date = gen_date()
    inv = gen_invoice_number()
    amount = gen_amount()
    company = gen_company()

    pii_set.update([name_text, phone_text, email, address])

    b.raw(f"SERVICE CONTRACT INVOICE\nProvider: {company}\n")
    b.raw("Invoice: ").decoy(inv, "INVOICE_NUMBER").raw(f"\nDate: {date}\n\n")
    b.raw("Client Name: ").entity(name_text, "PERSON", format=name_fmt).raw("\n")
    b.raw("Phone: ").entity(phone_text, "PHONE", format=phone_fmt).raw("\n")
    b.raw("Email: ").entity(email, "EMAIL").raw("\n")
    b.raw("Client Address: ").entity(address, "ADDRESS").raw("\n")
    write_bvn(b, pii_set, cued=random.random() < 0.60)
    write_nin(b, pii_set, cued=random.random() < 0.60)
    _write_order_id(b, order_id_spec, default_bare_prefix="Contract Code:")
    b.raw("\nService: Annual Software Maintenance\n")
    b.raw("Fee: ").decoy(amount, "AMOUNT").raw("\n")
    am_text, am_fmt = gen_person()
    pii_set.add(am_text)
    b.raw("Account Manager: ").entity(am_text, "PERSON", format=am_fmt).raw("\n")
    return b


def vendor_invoice_t4(b: DocBuilder, pii_set: set, order_id_spec: dict | None) -> DocBuilder:
    """Goods Receipt Note (GRN)."""
    name_text, name_fmt = gen_person()
    phone_text, phone_fmt = gen_phone()
    address = gen_address()
    date = gen_date()
    grn = gen_invoice_number()
    amount = gen_amount()

    pii_set.update([name_text, phone_text, address])

    b.raw("GOODS RECEIPT NOTE\n")
    b.raw("GRN No: ").decoy(grn, "INVOICE_NUMBER").raw("\n")
    _write_order_id(b, order_id_spec, default_bare_prefix="Receipt Code:")
    b.raw(f"Receipt Date: {date}\n\n")
    b.raw("Received From: ").entity(name_text, "PERSON", format=name_fmt).raw("\n")
    b.raw("Contact: ").entity(phone_text, "PHONE", format=phone_fmt).raw("\n")
    b.raw("Dispatch Address: ").entity(address, "ADDRESS").raw("\n")
    write_bvn(b, pii_set, cued=random.random() < 0.60)
    b.raw("\nGoods: 50 reams A4 paper\n")
    b.raw("Value: ").decoy(amount, "AMOUNT").raw("\n")
    ro_text, ro_fmt = gen_person()
    pii_set.add(ro_text)
    b.raw("Receiving Officer: ").entity(ro_text, "PERSON", format=ro_fmt).raw("\n")
    return b


def vendor_invoice_t5(b: DocBuilder, pii_set: set, order_id_spec: dict | None) -> DocBuilder:
    """Proforma Invoice."""
    first, last = gen_first(), gen_last()
    name_text, name_fmt = gen_person()
    phone_text, phone_fmt = gen_phone()
    email = gen_email(first, last)
    address = gen_address()
    date = gen_date()
    inv = gen_invoice_number()
    amount = gen_amount()
    company = gen_company()

    pii_set.update([name_text, phone_text, email, address])

    b.raw(f"PROFORMA INVOICE\nIssuer: {company}\n")
    b.raw("PI No: ").decoy(inv, "INVOICE_NUMBER").raw(f"\nDate: {date}\n\n")
    b.raw("Buyer Name: ").entity(name_text, "PERSON", format=name_fmt).raw("\n")
    b.raw("Phone: ").entity(phone_text, "PHONE", format=phone_fmt).raw("\n")
    b.raw("Email: ").entity(email, "EMAIL").raw("\n")
    b.raw("Buyer Address: ").entity(address, "ADDRESS").raw("\n")
    write_nin(b, pii_set, cued=random.random() < 0.60)
    _write_order_id(b, order_id_spec, default_bare_prefix="Quote Ref:")
    b.raw("\nDescription: Industrial Generator Supply\n")
    b.raw("Proforma Amount: ").decoy(amount, "AMOUNT").raw("\n")
    sr_text, sr_fmt = gen_person()
    pii_set.add(sr_text)
    b.raw("Sales Rep: ").entity(sr_text, "PERSON", format=sr_fmt).raw("\n")
    return b


# ---------------------------------------------------------------------------
# Template Registry
# ---------------------------------------------------------------------------
TEMPLATES = {
    "health_report": [
        health_report_t1,
        health_report_t2,
        health_report_t3,
        health_report_t4,
        health_report_t5,
    ],
    "hr_intake": [
        hr_intake_t1,
        hr_intake_t2,
        hr_intake_t3,
        hr_intake_t4,
        hr_intake_t5,
    ],
    "vendor_invoice": [
        vendor_invoice_t1,
        vendor_invoice_t2,
        vendor_invoice_t3,
        vendor_invoice_t4,
        vendor_invoice_t5,
    ],
}

# ---------------------------------------------------------------------------
# Split assignment (stratified, deterministic)
# ---------------------------------------------------------------------------

def assign_splits(doc_types: list) -> list:
    """
    Stratified split: 33 dev for health/hr, 34 dev for vendor_invoice.
    Total: 100 dev (33+33+34), 200 test (67+67+66).
    """
    dev_quota = {"health_report": 33, "hr_intake": 33, "vendor_invoice": 34}
    counts = {dt: 0 for dt in TEMPLATES}
    splits = []
    for dt in doc_types:
        if counts[dt] < dev_quota[dt]:
            splits.append("dev")
            counts[dt] += 1
        else:
            splits.append("test")
    return splits


# ---------------------------------------------------------------------------
# Plan ORDER_ID injection (exactly 150 total, 50 per doc_type)
# ---------------------------------------------------------------------------

def plan_order_ids() -> dict[str, list[dict | None]]:
    """
    For each doc_type, create a list of 100 entries (50 None, 50 dict).
    Across all 150 ORDER_IDs:
      - 50 'mobile' style
      - 50 '22' style
      - 50 'random' style
      - ~60% cued, ~40% bare
    """
    # 50 styles per doc_type
    doc_type_styles = {
        "health_report":  ["mobile"] * 17 + ["22"] * 17 + ["random"] * 16,
        "hr_intake":      ["mobile"] * 17 + ["22"] * 16 + ["random"] * 17,
        "vendor_invoice": ["mobile"] * 16 + ["22"] * 17 + ["random"] * 17,
    }

    result = {}
    for dt, styles in doc_type_styles.items():
        random.shuffle(styles)
        specs = []
        for style in styles:
            cued = random.random() < 0.60
            cue = random.choice(ORDER_ID_CUES) if cued else ""
            bare_pfx = random.choice(ORDER_ID_BARE_PREFIXES) if not cued else ""
            specs.append({
                "style": style,
                "cued": cued,
                "cue": cue,
                "bare_prefix": bare_pfx,
            })
        
        # 50 docs get an ORDER_ID, 50 docs get None
        full_list: list[dict | None] = specs + [None] * 50
        random.shuffle(full_list)
        result[dt] = full_list

    return result


# ---------------------------------------------------------------------------
# Main Generation Function
# ---------------------------------------------------------------------------

def generate():
    # Enforce deterministic PRNG start
    random.seed(SEED)
    Faker.seed(SEED)

    # Delete old raw files before regenerating
    if RAW_DIR.exists():
        for old_file in RAW_DIR.glob("*.txt"):
            old_file.unlink()

    # Plan ORDER_ID decoys: exactly 50 per doc_type (150 total)
    order_id_plans = plan_order_ids()
    order_id_ptrs = {dt: 0 for dt in TEMPLATES}

    # Build document list: 100 per doc_type
    doc_list = []
    for doc_type, templates in TEMPLATES.items():
        for i in range(100):
            fn = templates[i % len(templates)]
            doc_list.append((doc_type, fn))

    # Shuffle deterministically
    random.shuffle(doc_list)

    # Stratified split assignment
    doc_types_seq = [d[0] for d in doc_list]
    split_seq = assign_splits(doc_types_seq)

    ground_truth = []

    for idx, ((doc_type, template_fn), split) in enumerate(zip(doc_list, split_seq)):
        filename = f"{doc_type}_{idx:03d}.txt"
        b = DocBuilder()
        pii_set: set[str] = set()

        # Retrieve ORDER_ID spec for this doc (if assigned)
        raw_spec = order_id_plans[doc_type][order_id_ptrs[doc_type]]
        order_id_ptrs[doc_type] += 1

        order_id_spec = None
        if raw_spec is not None:
            # Generate the 11-digit value ensuring no collision with PII
            val = gen_order_id_value(raw_spec["style"], pii_set)
            order_id_spec = {
                "value": val,
                "style": raw_spec["style"],
                "cued": raw_spec["cued"],
                "cue": raw_spec["cue"],
                "bare_prefix": raw_spec["bare_prefix"],
            }

        # Build document text
        template_fn(b, pii_set, order_id_spec)
        text = b.build()

        # Write file with explicit utf-8 and \n newline
        file_path = RAW_DIR / filename
        with open(file_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

        # Immediate verification that tracked spans exactly match text
        for ent in b.entities:
            assert text[ent["start"]: ent["end"]] == ent["text"], (
                f"Span mismatch in {filename} for entity: {ent}"
            )
        for dec in b.decoys:
            assert text[dec["start"]: dec["end"]] == dec["text"], (
                f"Span mismatch in {filename} for decoy: {dec}"
            )

        ground_truth.append({
            "file": f"data/raw/{filename}",
            "doc_type": doc_type,
            "split": split,
            "length": len(text),
            "entities": b.entities,
            "decoys": b.decoys,
        })

    # Write ground truth JSON
    gt_path = DATA_DIR / "ground_truth.json"
    with open(gt_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(ground_truth, fh, indent=2, ensure_ascii=False)

    # Summary
    total_docs = len(ground_truth)
    dev_count = sum(1 for d in ground_truth if d["split"] == "dev")
    test_count = sum(1 for d in ground_truth if d["split"] == "test")
    total_order_ids = sum(
        sum(1 for dec in d["decoys"] if dec["type"] == "ORDER_ID")
        for d in ground_truth
    )

    print(f"Generated {total_docs} documents (dev={dev_count}, test={test_count})")
    print(f"Total ORDER_ID decoys: {total_order_ids}")
    for dt in TEMPLATES:
        d_cnt = sum(1 for d in ground_truth if d["doc_type"] == dt and d["split"] == "dev")
        t_cnt = sum(1 for d in ground_truth if d["doc_type"] == dt and d["split"] == "test")
        oid_cnt = sum(
            sum(1 for dec in d["decoys"] if dec["type"] == "ORDER_ID")
            for d in ground_truth if d["doc_type"] == dt
        )
        print(f"  {dt:<15}: dev={d_cnt}, test={t_cnt}, ORDER_IDs={oid_cnt}")


if __name__ == "__main__":
    generate()
