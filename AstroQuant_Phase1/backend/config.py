import os
from dotenv import load_dotenv

load_dotenv()

DATABENTO_API_KEY = os.getenv("DATABENTO_API_KEY")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
