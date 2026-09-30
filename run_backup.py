"""Create a Feast9 backup from the command line. The app makes its daily backup itself while
it's running (Backup & Data page settings); this script is for cron / Task Scheduler on a
server where that isn't enough — see BACKUP.md, including the restore-testing procedure that
makes a backup count as valid. Uses the same key (env var or the key file created in the
app) and the same copy-folder / keep settings."""
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
