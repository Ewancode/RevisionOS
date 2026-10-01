"""Optional LibreOffice rendering of slides (ARCHITECTURE.md section 7).

python-pptx cannot read Office equation objects. When LibreOffice is
installed, slides are converted to PDF and rendered so Claude can read them;
otherwise those slides are flagged for review.
"""

import shutil
import subprocess
from pathlib import Path

CONVERT_TIMEOUT_SECONDS = 180


def libreoffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def office_to_pdf(source: Path, workdir: Path) -> Path | None:
    binary = libreoffice()
    if binary is None:
        return None
    # A private profile directory keeps concurrent conversions independent.
    profile = (workdir / "lo-profile").resolve().as_uri()
    subprocess.run(  # noqa: S603  # fixed binary and arguments, no shell
        [
            binary,
            f"-env:UserInstallation={profile}",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(workdir),
            str(source),
        ],
        capture_output=True,
        timeout=CONVERT_TIMEOUT_SECONDS,
        check=True,
    )
    converted = workdir / (source.stem + ".pdf")
    return converted if converted.exists() else None
