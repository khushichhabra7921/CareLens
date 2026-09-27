"""Find and mask identifiers in text. Defence in depth: the payload sent to the LLM is already
aggregate-only (see minimize.py); this catches anything that slipped through, in both the
outbound payload and the LLM's response.

Types and what happens to them:
  uuid, email, ssn, phone, name  -> DIRECT identifiers: replaced with [UUID], [EMAIL], ...
  date                            -> generalised to year-month ("2024-03-15" -> "2024-03")
  zip                             -> 5-digit ZIP codes replaced with [ZIP]
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from app.privacy.tokens import COMMON_WORDS, MIN_TOKEN_LENGTH, WORD, normalise, token_hash

DIRECT_TYPES = ("uuid", "email", "ssn", "phone", "name")

MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|"
          "December")

# Order matters: UUIDs first (they contain digit runs other patterns could grab), then
# emails, SSNs and phones, then dates, then ZIPs.
PATTERNS = [
    ("uuid", re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
                        re.IGNORECASE)),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("ssn", re.compile(r"(?<!\d)\d{3}[- ]\d{2}[- ]\d{4}(?!\d)")),
    ("phone", re.compile(r"(?<![\d-])(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}"
                         r"(?![\d-])")),
]
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z?)?\b")
US_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
LONG_DATE = re.compile(rf"\b({MONTHS}) (\d{{1,2}}),? (\d{{4}})\b")
# A 5-digit number (or ZIP+4) standing alone: not part of a bigger number, money or a decimal.
ZIP = re.compile(r"(?<![\d$.,])\d{5}(?:-\d{4})?(?![\d,.%])")

MASKS = {"uuid": "[UUID]", "email": "[EMAIL]", "ssn": "[SSN]", "phone": "[PHONE]",
         "name": "[NAME]", "zip": "[ZIP]"}


@dataclass
class RedactionResult:
    text: str
    counts: Counter = field(default_factory=Counter)


class Redactor:
    def __init__(self, name_hashes: set[str], salt: str):
        self.name_hashes = name_hashes
        self.salt = salt

    def is_name(self, word: str) -> bool:
        token = normalise(word)
        return (len(token) >= MIN_TOKEN_LENGTH and token not in COMMON_WORDS
                and token_hash(token, self.salt) in self.name_hashes)

    def redact(self, text: str, allowed_numbers: frozenset = frozenset()) -> RedactionResult:
        """Return the masked text and how many of each type were found.
        allowed_numbers: 5-digit values that are known data (e.g. a cost of 45200), not ZIPs."""
        counts = Counter()

        def sub(kind, pattern, replacement, value):
            def replace(match):
                counts[kind] += 1
                return replacement(match) if callable(replacement) else replacement
            return pattern.sub(replace, value)

        for kind, pattern in PATTERNS:
            text = sub(kind, pattern, MASKS[kind], text)
        text = sub("date", ISO_DATE, lambda m: f"{m[1]}-{m[2]}", text)
        text = sub("date", US_DATE, lambda m: f"{m[3]}-{int(m[1]):02d}", text)
        text = sub("date", LONG_DATE, lambda m: f"{m[1]} {m[3]}", text)

        def zip_replace(match):
            if int(match[0][:5]) in allowed_numbers:
                return match[0]
            counts["zip"] += 1
            return MASKS["zip"]
        text = ZIP.sub(zip_replace, text)

        def name_replace(match):
            if self.is_name(match[0]):
                counts["name"] += 1
                return MASKS["name"]
            return match[0]
        text = WORD.sub(name_replace, text)
        return RedactionResult(text, counts)

    def redact_strings(self, obj, allowed_numbers: frozenset = frozenset()):
        """Redact every string inside a JSON-like structure (dicts, lists, strings; numbers are
        left alone). Returns (new object, Counter of what was found)."""
        total = Counter()

        def walk(value):
            if isinstance(value, str):
                result = self.redact(value, allowed_numbers)
                total.update(result.counts)
                return result.text
            if isinstance(value, dict):
                return {walk(k): walk(v) for k, v in value.items()}
            if isinstance(value, list):
                return [walk(v) for v in value]
            return value
        return walk(obj), total


def direct_identifiers(counts: Counter) -> dict[str, int]:
    """Only the direct-identifier part of a count (names, SSNs, ...), without dates and ZIPs."""
    return {k: v for k, v in counts.items() if k in DIRECT_TYPES and v}
