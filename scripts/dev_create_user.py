"""Create a test user for local runs and save the 2FA QR code as an image.

Run through scripts/dev_server.ps1 so the environment is set:
  powershell -ExecutionPolicy Bypass -File scripts\\dev_server.ps1 create-user prawnik@kancelaria.test admin
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import qrcode  # noqa: E402

from app.auth import totp_uri  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import make_sessionmaker  # noqa: E402
from app.main import create_user  # noqa: E402
from app.services import Services  # noqa: E402


def main() -> int:
    email = sys.argv[1] if len(sys.argv) > 1 else "prawnik@kancelaria.test"
    role = sys.argv[2] if len(sys.argv) > 2 else "lawyer"
    settings = Settings.from_env()
    services = Services(settings, make_sessionmaker(settings.database_url), llm_factory=lambda: None)
    password = secrets.token_urlsafe(12)
    user = create_user(services, email, password, role)
    uri = totp_uri(user.totp_secret, user.email)
    qr_path = settings.data_dir / f"2fa_{user.email.split('@')[0]}.png"
    qrcode.make(uri).save(qr_path)
    print(f"E-mail: {user.email}")
    print(f"Haslo:  {password}")
    print(f"Rola:   {user.role}")
    print(f"QR 2FA: {qr_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
