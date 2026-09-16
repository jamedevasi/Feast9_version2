"""Create a Feast9 backup. Schedule this nightly via cron or Windows Task Scheduler — see
BACKUP.md for scheduling examples, off-site destination setup, and the restore-testing
procedure that makes a backup count as valid."""
import sys

from app import db
from app.backup import BackupError, create_backup


def main():
    try:
        row = create_backup()
    except BackupError as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Backup {row['status']}: {row['file_path']} ({row['file_size']} bytes, offsite={row['offsite_status'] or 'not_configured'})")


if __name__ == "__main__":
    db.init_db()
    main()
