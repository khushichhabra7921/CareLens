"""Build app.name_token_hashes: keyed hashes of every patient name token, for the redactor.

Privileged: runs as carelens_loader, the only role that can read phi. The web app only ever
sees the hashes, and without NAME_HASH_SALT (kept outside the database) they can't be reversed
by guessing names.

Excluded from the list (so they are never treated as names):
  - every word that appears in the published aggregate data (reporting views and their
    comments), e.g. race "white" or payer "Blue Cross Blue Shield": these must pass through;
  - COMMON_WORDS in app/privacy/tokens.py (everyday prose such as "will" or "may").

Runs automatically at the end of scripts/load_data.py. Manual run:
    py -3.12 scripts/build_name_hashes.py
"""

import sys

import psycopg
from psycopg import sql

import refresh_views
from common import REPO_ROOT, connect, settings

sys.path.insert(0, str(REPO_ROOT))
from app.privacy.tokens import COMMON_WORDS, MIN_TOKEN_LENGTH, normalise, token_hash, words  # noqa: E402,I001


def reporting_vocabulary(conn: psycopg.Connection) -> set[str]:
    vocab = set()
    for a in refresh_views.list_analyses():
        view = sql.Identifier("reporting", a.view)
        for row in conn.execute(sql.SQL("SELECT * FROM {}").format(view)):
            vocab.update(normalise(w) for v in row if isinstance(v, str) for w in words(v))
        vocab.update(normalise(w) for text in a.header.values() for w in words(text))
    return vocab


def rebuild(conn: psycopg.Connection, salt: str) -> dict:
    """Replace the hash list (inside the caller's transaction). Returns counts for the log."""
    tokens = set()
    for row in conn.execute("SELECT first_name, middle_name, last_name, maiden_name "
                            "FROM phi.patient_identifiers"):
        tokens.update(normalise(w) for part in row if part for w in words(part))
    tokens = {t for t in tokens if len(t) >= MIN_TOKEN_LENGTH}
    vocab = reporting_vocabulary(conn)
    kept = tokens - vocab - COMMON_WORDS
    conn.execute("TRUNCATE app.name_token_hashes")
    with conn.cursor() as cur:
        with cur.copy("COPY app.name_token_hashes (token_hash) FROM STDIN") as copy:
            for token in sorted(kept):
                copy.write_row([token_hash(token, salt)])
    return {"name_tokens": len(tokens), "excluded_data_vocabulary": len(tokens & vocab),
            "excluded_common_words": len((tokens - vocab) & COMMON_WORDS), "hashed": len(kept)}


def salt_or_exit() -> str:
    salt = settings().name_hash_salt
    if salt is None or len(salt.get_secret_value()) < 20:
        raise SystemExit("Set NAME_HASH_SALT (20+ characters) in .env first (see .env.example).")
    return salt.get_secret_value()


def main() -> None:
    with connect("loader") as conn:
        stats = rebuild(conn, salt_or_exit())
    print("Name-token hashes rebuilt:", stats)


if __name__ == "__main__":
    main()
