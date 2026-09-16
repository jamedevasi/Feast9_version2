import os

DEFAULT_SECRET_KEY = "dev-insecure-default-change-me"

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))
DB_PATH = os.path.join(DATA_DIR, "feast9.db")
SECRET_KEY = os.environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)
