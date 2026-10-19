import os
import secrets
from dotenv import load_dotenv

# Load optional environment variables from .env if present
load_dotenv()

class Config:
    # Rotate SECRET_KEY: use environment variable if set, otherwise generate secure 256-bit token
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    
    # MySQL Database
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_PORT = int(os.environ.get('DB_PORT', 3306))
    DB_USER = os.environ.get('DB_USER', 'root')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
    DB_NAME = os.environ.get('DB_NAME', 'sysrealm')
    
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Simulation defaults
    DEFAULT_RAM_GB = 16
    DEFAULT_STORAGE_GB = 100
    DEFAULT_TIME_QUANTUM = 2
    
    DEBUG = os.environ.get('FLASK_DEBUG', 'False') == 'True'
