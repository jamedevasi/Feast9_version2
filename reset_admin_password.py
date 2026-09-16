"""Emergency CLI: reset the admin password without needing to log in."""
import getpass
import sys

from app import db
from app.auth import hash_password


def main():
    admin = db.get_admin()
    if admin is None:
        print("No admin account exists yet. Run the app and complete /setup instead.")
        sys.exit(1)

    password = getpass.getpass("New admin password: ")
    confirm = getpass.getpass("Confirm new password: ")
    if password != confirm:
        print("Passwords do not match.")
        sys.exit(1)
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        sys.exit(1)

    db.update_admin_password(hash_password(password))
    print(f"Password reset for admin '{admin['username']}'.")


if __name__ == "__main__":
    db.init_db()
    main()
