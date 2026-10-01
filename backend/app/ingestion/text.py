"""Text hygiene for anything extracted from files or returned by Claude."""

import re

# C0 control characters (except tab, newline, carriage return) and DEL. They
# leak from broken font encodings, carry no meaning, and PostgreSQL rejects
# NUL in text columns outright.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(text: str) -> str:
    return _CONTROL.sub("", text)
