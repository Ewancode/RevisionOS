"""Display-safe filenames. They are only ever shown, never used as paths."""

import re
import unicodedata

MAX_LENGTH = 200
# Control characters and bidirectional overrides (which can disguise an
# extension, e.g. "notes‮gpj.exe").
_UNSAFE = re.compile(r"[\x00-\x1f\x7f‎‏‪-‮⁦-⁩]")


def sanitise_filename(raw: str) -> str:
    name = unicodedata.normalize("NFC", raw)
    name = re.split(r"[\\/]", name)[-1]  # drop any directory part
    name = re.sub(r"\s+", " ", name)  # tabs and newlines become spaces first
    name = _UNSAFE.sub("", name).strip(" .")
    if not name:
        return "upload"
    if len(name) > MAX_LENGTH:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            name = stem[: MAX_LENGTH - len(ext) - 1].rstrip() + "." + ext
        else:
            name = name[:MAX_LENGTH]
    return name


def extension(name: str) -> str:
    _, dot, ext = name.rpartition(".")
    return ext.lower() if dot else ""
