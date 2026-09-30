import os

from app import create_app
from app.backup import start_backup_scheduler

app = create_app()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    # With debug on, Flask's reloader runs this file twice (a watcher + the real server);
    # start the daily-backup timer only in the process that serves requests.
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_backup_scheduler()
    app.run(host="127.0.0.1", port=5000, debug=debug)
