"""How words are turned into name-token hashes. Shared by the privileged build script and the
app's redactor, so both normalise and hash a word in exactly the same way."""

import hashlib
import hmac
import re
import unicodedata

# A "word" = a run of letters (any alphabet). "Smith-Jones" -> "Smith", "Jones".
WORD = re.compile(r"[^\W\d_]+")
MIN_TOKEN_LENGTH = 2


def normalise(token: str) -> str:
    """Lower-case and strip accents, so 'José', 'JOSE' and 'jose' are the same token."""
    decomposed = unicodedata.normalize("NFKD", token)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def words(text: str) -> list[str]:
    return WORD.findall(text)


def token_hash(token: str, salt: str) -> str:
    """HMAC-SHA256 of the normalised token, keyed with the secret salt. HMAC (rather than
    sha256(salt + token)) is the standard construction for a keyed hash."""
    return hmac.new(salt.encode(), normalise(token).encode(), hashlib.sha256).hexdigest()


# Everyday English words an analyst's prose might contain that are ALSO first names or
# surnames (e.g. "rates will rise", "may reflect", "costs rose", "a long stay"). They are not
# treated as names, or ordinary sentences would be masked. Words that appear in the published
# data itself (race "white", payer "Blue Cross ...") are excluded separately and automatically
# by scripts/build_name_hashes.py. Trade-off: a patient called e.g. "Will Young" is not caught by
# the redactor. Data minimisation (names are never sent) remains the primary control.
# Kept deliberately short; common surnames like Smith or Jones must NOT be added here.
COMMON_WORDS = frozenset("""
will may mark rose long young hope just best new more early fair poor little small short
strong major power trust case rich bill price cross day march april june july august
summer winter spring dawn chase free good sharp gray grey green brown white black gold
""".split())
