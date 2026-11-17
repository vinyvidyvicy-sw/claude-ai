"""Bootstrap CLI:  python -m app.cli create-admin <username>

The password is read from a hidden prompt (or stdin with --password-stdin). It is never
accepted as a command-line argument, so it cannot land in shell history or `ps` output.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from . import audit, users
from .db import Database
from .settings import Settings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ca = sub.add_parser("create-admin", help="create a user (first-run bootstrap)")
    ca.add_argument("username")
    ca.add_argument("--role", default="admin", choices=users.ROLES)
    ca.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    args = ap.parse_args(argv)

    settings = Settings.from_env()
    db = Database(settings.db_path)
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            print("Passwords do not match.", file=sys.stderr)
            return 1
    try:
        with db.conn() as c:
            users.create_user(c, settings, username=args.username, password=password, role=args.role,
                              created_by="cli", must_change_password=False)
            audit.record(c, actor="cli", action="user.create", target=args.username,
                         params={"role": args.role}, result="success")
    except users.UserError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Created {args.role} '{args.username}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
