"""Admin commands.

  python -m app.cli create-user admin@kancelaria.pl --role admin   (asks for the password)
  python -m app.cli purge-expired                                  (run daily, e.g. from cron / systemd timer)
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app.auth import totp_uri


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin wrapper, logic tested elsewhere
    from app.factory import build_services
    from app.main import create_user

    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    create = sub.add_parser("create-user")
    create.add_argument("email")
    create.add_argument("--role", choices=("lawyer", "admin"), default="lawyer")
    sub.add_parser("purge-expired")
    args = parser.parse_args(argv)

    services = build_services()
    if args.cmd == "create-user":
        password = getpass.getpass("Hasło (min. 12 znaków): ")
        if password != getpass.getpass("Powtórz hasło: "):
            print("Hasła nie są zgodne.", file=sys.stderr)
            return 1
        user = create_user(services, args.email, password, args.role)
        print(f"Utworzono {user.email} ({user.role}).")
        print("Dodaj w aplikacji uwierzytelniającej (TOTP):")
        print(totp_uri(user.totp_secret, user.email))
        return 0
    if args.cmd == "purge-expired":
        print(f"Usunięto spraw: {services.purge_expired()}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
