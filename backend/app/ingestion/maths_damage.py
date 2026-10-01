"""How badly did plain text extraction damage a page's mathematics?

Text layers in maths PDFs often lose structure: fractions flatten
("S_n = n/2 (n+1)" becomes "Sn = n2(n+ 1)"), symbols map to private-use
glyphs, and display equations shatter into lines of stray operators
("1 × 2 2 3 4 × × × −1"). None of this can be repaired from the text alone,
so the score only decides *which* pages are re-read from their image.

Signals (each in [0, 1] after normalising by its saturation):
  maths_font        share of characters set in maths fonts (CMMI, Symbol...)
  orphan_lines      share of lines made only of short tokens / symbols
  operator_density  maths operators per character
  broken_glyphs     U+FFFD, private-use and control characters per character

score = min(1, sum(weight_i * min(1, signal_i / saturation_i)))
Weights, saturations and the threshold live in config/platform.yaml.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.core.config import MathsDamageConfig

MATHS_FONT = re.compile(
    r"CMMI|CMSY|CMEX|CMBSY|MSAM|MSBM|LMMath|Symbol|MTSY|MTMI|MT\s?Extra|STIX|"
    r"Cambria\s?Math|MathJax|Euclid|Asana|XITS|TeXGyre\w*Math|rsfs|eufm",
    re.IGNORECASE,
)
# The true minus sign only: ASCII hyphens are everywhere in prose.
OPERATORS = set("=+−×÷∑∏∫∮√≤≥≠≈∞∂∇∈∉⊂⊆∪∩→←↔⇒⇔·^_±∓∀∃¬∧∨")
_TOKEN_MAX = 2


@dataclass(frozen=True)
class Span:
    text: str
    font: str


@dataclass(frozen=True)
class DamageReport:
    score: float
    signals: dict[str, float]


def _is_broken(ch: str) -> bool:
    """Replacement, private-use and control characters: signs that a font's
    glyphs could not be mapped back to Unicode."""
    code = ord(ch)
    return ch == "\ufffd" or 0xE000 <= code <= 0xF8FF or (code < 32 and ch not in "\t\n\r")


def _is_orphan(line: str) -> bool:
    tokens = line.split()
    if not tokens:
        return False
    # A line of only very short tokens that includes a digit or operator:
    # the debris of an equation laid out as separate glyphs.
    short = all(len(t) <= _TOKEN_MAX for t in tokens)
    mathy = any(ch.isdigit() or ch in OPERATORS for ch in line)
    return short and mathy


Line = Sequence[Span]


def measure(lines: Iterable[Line], config: MathsDamageConfig) -> DamageReport:
    """Score a page given as lines of font-tagged spans."""
    kept = [line for line in lines if "".join(s.text for s in line).strip()]
    spans = [span for line in kept for span in line]
    chars = [c for s in spans for c in s.text if not c.isspace()]
    total = len(chars)
    if total == 0:
        return DamageReport(0.0, {k: 0.0 for k in config.weights.model_dump()})

    maths_chars = sum(
        sum(not c.isspace() for c in s.text) for s in spans if MATHS_FONT.search(s.font)
    )
    texts = ["".join(s.text for s in line) for line in kept]
    raw = {
        "maths_font": maths_chars / total,
        "orphan_lines": sum(_is_orphan(t) for t in texts) / len(texts),
        "operator_density": sum(c in OPERATORS for c in chars) / total,
        "broken_glyphs": sum(_is_broken(c) for c in chars) / total,
    }
    weights = config.weights.model_dump()
    saturation = config.saturation.model_dump()
    normalised = {k: min(1.0, v / saturation[k]) for k, v in raw.items()}
    score = min(1.0, sum(weights[k] * normalised[k] for k in raw))
    return DamageReport(round(score, 4), {k: round(v, 4) for k, v in raw.items()})


def measure_text(text: str, config: MathsDamageConfig) -> DamageReport:
    """For text without font information (Office, plain text)."""
    return measure([[Span(line, "")] for line in text.splitlines()], config)
