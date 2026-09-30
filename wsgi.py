from app import create_app
from app.backup import start_backup_scheduler

app = create_app()
# One timer per worker process is fine — db.claim_backup_run lets only one run each day's backup.
start_backup_scheduler()
