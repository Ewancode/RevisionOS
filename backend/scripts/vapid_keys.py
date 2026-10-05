"""Generate Web Push (VAPID) keys and add them to .env: ``make vapid-keys``.

Only keys that are missing or blank are written; existing ones are kept.
The private key is never printed.
"""

import base64
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ENV = Path(__file__).resolve().parents[2] / ".env"
# A contact for the push services. Change it to a real address once deployed.
DEFAULT_SUBJECT = "mailto:admin@localhost"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return b64url(public), b64url(private)


def has_value(text: str, name: str) -> bool:
    return re.search(rf"^{name}=\S+", text, re.MULTILINE) is not None


def main() -> int:
    if not ENV.exists():
        print(".env not found: copy .env.example to .env first.", file=sys.stderr)
        return 1
    text = ENV.read_text(encoding="utf-8")
    public, private = generate()
    wanted = {
        "VAPID_PUBLIC_KEY": public,
        "VAPID_PRIVATE_KEY": private,
        "VAPID_SUBJECT": DEFAULT_SUBJECT,
    }
    if has_value(text, "VAPID_PUBLIC_KEY") != has_value(text, "VAPID_PRIVATE_KEY"):
        print(
            "Only one VAPID key is set in .env; remove it to generate a fresh pair.",
            file=sys.stderr,
        )
        return 1
    added = []
    for name, value in wanted.items():
        if has_value(text, name):
            continue
        if re.search(rf"^{name}=\s*$", text, re.MULTILINE):
            text = re.sub(rf"^{name}=\s*$", f"{name}={value}", text, count=1, flags=re.MULTILINE)
        else:
            text = text.rstrip("\n") + f"\n{name}={value}\n"
        added.append(name)
    ENV.write_text(text, encoding="utf-8", newline="\n")
    if added:
        print(f"Added to .env: {', '.join(added)}. Restart the api and scheduler to turn push on.")
    else:
        print("VAPID keys are already set in .env; nothing changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
