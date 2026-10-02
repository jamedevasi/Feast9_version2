"""Emergency CLI: reset the admin password without needing to log in.

Run on the computer Feast9 runs on (with the same DATA_DIR). The same password rules as
everywhere else apply, the change is written to the audit log (with no user — nobody was
signed in), every existing session of that account ends and any lockout is lifted.
"""
import getpass
import sys

from app import db
from app.auth import hash_password, password_errors


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
    errors = password_errors(password, admin["username"])
    if errors:
        print("\n".join(errors))
        sys.exit(1)

    db.update_user_password(admin["id"], hash_password(password), how="reset on the Feast9 computer")
    print(f"Password reset for admin '{admin['username']}'.")


if __name__ == "__main__":
    db.init_db()
    main()
