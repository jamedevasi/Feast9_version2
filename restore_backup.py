"""Restore a Feast9 backup.

Run this against a CLEAN/STAGING DATA_DIR to restore-test a backup before ever trusting it
against production — a backup that has never been restore-tested is not considered valid
(feast9_v2_agents.md §11, §14). See BACKUP.md for the full procedure.

This is a CLI-only operation, deliberately not exposed over the web — restoring overwrites
the live database.
"""
import argparse
import sys

from app import db
from app.backup import BackupError, restore_backup


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("backup_file", help="Path to a feast9-backup-*.tar.enc file")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing database at DATA_DIR")
    args = parser.parse_args()

    try:
        restore_backup(args.backup_file, force=args.force)
    except BackupError as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print("Restore complete. A safety copy of the previous database (if any) was kept alongside it.")


if __name__ == "__main__":
    db.init_db()
    main()
