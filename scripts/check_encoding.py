"""Check that every file tracked by git is valid UTF-8, without a byte-order mark.

Why: a UTF-16 .gitignore looks fine in an editor, but git can't read it and
silently ignores nothing. This script catches that (and any other non-UTF-8 file).

Usage:  py -3.12 scripts/check_encoding.py      (exit code 1 if any file fails)
"""

import subprocess
import sys

BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".jar", ".zip", ".pdf"}
BOMS = {
    b"\xef\xbb\xbf": "UTF-8 BOM",
    b"\xff\xfe": "UTF-16 LE BOM",
    b"\xfe\xff": "UTF-16 BE BOM",
}


def tracked_files() -> list[str]:
    # --cached: committed/staged files; --others --exclude-standard: new, not-ignored files
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True, text=True, check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def problem_with(path: str) -> str | None:
    with open(path, "rb") as f:
        data = f.read()
    for bom, name in BOMS.items():
        if data.startswith(bom):
            return f"starts with a {name}"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as err:
        return f"is not valid UTF-8 ({err.reason} at byte {err.start})"
    return None


def main() -> int:
    failures = 0
    for path in tracked_files():
        if any(path.lower().endswith(ext) for ext in BINARY_EXTENSIONS):
            continue
        problem = problem_with(path)
        if problem:
            print(f"FAIL {path} {problem}")
            failures += 1
    print(f"{failures} file(s) with encoding problems.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
