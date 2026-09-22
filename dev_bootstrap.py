"""Local dev convenience: create the bootstrap admin account (if none exists yet) and seed
demo data in one command, instead of clicking through /setup then running seed_demo_data.py
by hand. Safe to re-run — an existing admin account is left untouched (credentials are only
printed, never reset) and seed_demo_data.run() is already idempotent.

    python dev_bootstrap.py                 # default dev credentials
    python dev_bootstrap.py --username me --password "Something123!"
"""
import argparse
import sys

import seed_demo_data
from app import db
from app.auth import hash_password

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "DevPassword123!"
DEFAULT_SECURITY_QUESTION = "What is this clinic's name?"
DEFAULT_SECURITY_ANSWER = "Feast9"


def _bootstrap_admin(username, password, security_question, security_answer):
    existing = db.get_admin()
    if existing is not None:
        print(f"Admin account already exists (username: '{existing['username']}') — leaving it as is.")
        return existing["username"], None

    if len(password) < 8:
        print("Password must be at least 8 characters.")
        sys.exit(1)

    db.create_admin(
        username,
        hash_password(password),
        security_question,
        hash_password(security_answer),
    )
    print(f"Created admin account — username: '{username}', password: '{password}'.")
    return username, password


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default=DEFAULT_USERNAME, help="Bootstrap admin username (default: admin)")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Bootstrap admin password (default: a fixed dev password)")
    parser.add_argument("--security-question", default=DEFAULT_SECURITY_QUESTION)
    parser.add_argument("--security-answer", default=DEFAULT_SECURITY_ANSWER)
    parser.add_argument("--no-seed", action="store_true", help="Skip seeding demo data")
    args = parser.parse_args()

    db.init_db()
    username, password = _bootstrap_admin(
        args.username, args.password, args.security_question, args.security_answer
    )

    if not args.no_seed:
        seed_demo_data.run()

    print()
    print("Ready — run `python run.py` and log in at http://127.0.0.1:5000/login")
    if password:
        print(f"  username: {username}")
        print(f"  password: {password}")
    else:
        print(f"  username: {username} (existing account — use its current password)")


if __name__ == "__main__":
    main()
