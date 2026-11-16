import argparse
import getpass
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash

from app import BASE_DIR, DEPARTMENTS, create_app


def main():
    parser = argparse.ArgumentParser(description="SmartCivicAI database and account tools")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db", help="Create the SQLite schema")
    create_user = commands.add_parser("create-user", help="Create a municipal or admin account")
    create_user.add_argument("--role", choices=("municipal", "department", "admin"), required=True)
    create_user.add_argument("--department", choices=sorted(DEPARTMENTS))
    create_user.add_argument("--email", required=True)
    create_user.add_argument("--name", required=True)
    reset_password = commands.add_parser(
        "reset-password",
        help="Reset the password for an existing municipal or department account",
    )
    reset_password.add_argument("--email", required=True)
    args = parser.parse_args()
    if args.command == "create-user":
        if args.role == "department" and not args.department:
            parser.error("--department is required when --role is department.")
        if args.role != "department" and args.department:
            parser.error("--department is only valid when --role is department.")

    app = create_app()
    if args.command == "init-db":
        print(f"SQLite database initialized at {Path(app.config['DATABASE']).resolve()}")
        return 0

    if args.command == "reset-password":
        password = getpass.getpass("New password (10-128 characters): ")
        confirmation = getpass.getpass("Confirm new password: ")
        if password != confirmation:
            print("Passwords do not match.", file=sys.stderr)
            return 1
        try:
            updated = reset_municipal_password(
                app.config["DATABASE"], args.email, password
            )
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
        if not updated:
            print(
                "No municipal or department account was found for that email.",
                file=sys.stderr,
            )
            return 1
        print(f"Password reset for municipal or department account {args.email.strip()}.")
        return 0

    password = getpass.getpass("Temporary account password (10-128 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    if not 10 <= len(password) <= 128:
        print("Password must contain between 10 and 128 characters.", file=sys.stderr)
        return 1
    email = args.email.strip().lower()
    if "@" not in email:
        print("Enter a valid email address.", file=sys.stderr)
        return 1

    connection = sqlite3.connect(app.config["DATABASE"])
    try:
        connection.execute(
            """INSERT INTO users
               (id, name, email, phone, password_hash, role, department, created_at)
               VALUES (?, ?, ?, NULL, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                args.name.strip(),
                email,
                generate_password_hash(password),
                "municipal" if args.role == "department" else args.role,
                args.department,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        connection.commit()
    except sqlite3.IntegrityError:
        print("An account with this email already exists.", file=sys.stderr)
        return 1
    finally:
        connection.close()
    account_type = f"{args.department} department" if args.role == "department" else args.role
    print(f"Created {account_type} account for {email}.")
    return 0


def reset_municipal_password(database_path, email, password):
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        raise ValueError("Password must contain between 10 and 128 characters.")
    normalized_email = email.strip().lower()
    if "@" not in normalized_email:
        raise ValueError("Enter a valid email address.")

    connection = sqlite3.connect(database_path)
    try:
        account = connection.execute(
            """SELECT id FROM users
               WHERE email = ? COLLATE NOCASE AND role = 'municipal'""",
            (normalized_email,),
        ).fetchone()
        if account is None:
            return False
        result = connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ? AND role = 'municipal'",
            (generate_password_hash(password), account[0]),
        )
        connection.commit()
        return result.rowcount == 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
