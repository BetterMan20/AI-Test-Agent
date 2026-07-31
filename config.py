import os

from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("MOONSHOT_API_KEY")

BASE_URL = os.getenv("MOONSHOT_BASE_URL")

MODEL = os.getenv("MODEL")