"""A table of tricky redaction cases (no database needed)."""

import pytest

from app.privacy.redactor import Redactor, direct_identifiers
from app.privacy.tokens import normalise, token_hash

SALT = "test-name-hash-salt-0123456789"
# As if built from phi: "Mary Ellen Smith-Jones", "José García", "Grace Lee", "Will Young".
NAMES = {"mary", "ellen", "smith", "jones", "jose", "garcia", "grace", "lee", "will", "young"}
redactor = Redactor({token_hash(n, SALT) for n in NAMES}, SALT)


@pytest.mark.parametrize("text, expected, kind", [
    # --- SSNs
    ("SSN 123-45-6789 on file", "SSN [SSN] on file", "ssn"),
    ("ssn 123 45 6789", "ssn [SSN]", "ssn"),
    ("id 1234-56-7890", "id 1234-56-7890", None),             # 4 digits first: not an SSN
    # --- phones (US formats)
    ("call (617) 555-0123", "call [PHONE]", "phone"),
    ("call 617-555-0123 now", "call [PHONE] now", "phone"),
    ("call +1 617 555 0123", "call [PHONE]", "phone"),
    ("4,274,460 observations", "4,274,460 observations", None),  # a big number, not a phone
    # --- email and UUID
    ("mail jane.doe+x@example.co.uk", "mail [EMAIL]", "email"),
    ("patient 242a18ab-283e-5f14-b9df-b793005574ea", "patient [UUID]", "uuid"),
    ("PATIENT 242A18AB-283E-5F14-B9DF-B793005574EA", "PATIENT [UUID]", "uuid"),
    # --- dates: generalised to year-month, not removed
    ("admitted 2024-03-15", "admitted 2024-03", "date"),
    ("at 2024-03-15T10:15:00Z", "at 2024-03", "date"),
    ("on 3/15/2024", "on 2024-03", "date"),
    ("on March 15, 2024", "on March 2024", "date"),
    ("data through 2024-03", "data through 2024-03", None),   # already year-month
    # --- ZIP codes
    ("lives in 02139", "lives in [ZIP]", "zip"),
    ("zip 02139-4307", "zip [ZIP]", "zip"),
    ("cost $45200", "cost $45200", None),                      # money, not a ZIP
    ("rate 16.62345%", "rate 16.62345%", None),                # a decimal, not a ZIP
    # --- names
    ("Patient Mary Smith-Jones", "Patient [NAME] [NAME]-[NAME]", "name"),
    ("JOSÉ garcía", "[NAME] [NAME]", "name"),                  # case and accents ignored
    ("Jose Garcia", "[NAME] [NAME]", "name"),                  # accents stripped match too
    ("Maryland and Leeds", "Maryland and Leeds", None),        # a name inside a word is not a name
    ("rates will rise for young adults", "rates will rise for young adults", None),  # common words
    ("Dr Grace", "Dr [NAME]", "name"),
])
def test_redaction_cases(text, expected, kind):
    result = redactor.redact(text)
    assert result.text == expected
    if kind:
        assert result.counts[kind] >= 1
    else:
        assert sum(result.counts.values()) == 0


def test_five_digit_numbers_known_to_be_data_are_not_zips():
    assert redactor.redact("cost 45200 total", frozenset({45200.0})).text == "cost 45200 total"


def test_counts_by_type():
    result = redactor.redact("Mary (617) 555-0123, 123-45-6789, 2024-01-02 and 2024-02-03")
    assert dict(result.counts) == {"name": 1, "phone": 1, "ssn": 1, "date": 2}
    assert direct_identifiers(result.counts) == {"name": 1, "phone": 1, "ssn": 1}


def test_redact_strings_walks_nested_data_and_leaves_numbers_alone():
    data = {"rows": [["Mary", 12, 3.5], ["ok", None, True]], "note": "call 617-555-0123"}
    cleaned, counts = redactor.redact_strings(data)
    assert cleaned == {"rows": [["[NAME]", 12, 3.5], ["ok", None, True]], "note": "call [PHONE]"}
    assert dict(counts) == {"name": 1, "phone": 1}


def test_hashing_needs_the_secret_salt():
    # Same name, different salt -> different hash, so the list can't be checked by guessing.
    assert token_hash("mary", SALT) != token_hash("mary", "another-salt-0123456789")
    assert normalise("JOSÉ") == "jose"
