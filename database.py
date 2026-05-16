import os

import pymysql
import pymysql.err

# 1. DATABASE CONNECTION
def get_db_connection():
    try:
        connection = pymysql.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            user=os.getenv('DB_USER', 'root'),
            password=os.getenv('DB_PASSWORD', ''),
            database=os.getenv('DB_NAME', 'qcms_db'),
            port=int(os.getenv('DB_PORT', '3306')),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            connect_timeout=5
        )
        return connection
    except pymysql.err.OperationalError as e:
        print(f"Database connection error: {e}")
        return None

# 2. EMAIL CONFIGURATION (BREVO API)
BREVO_API_KEY = os.getenv('BREVO_API_KEY', '')
SENDER_EMAIL = os.getenv('SENDER_EMAIL', 'asr082239@gmail.com')
SENDER_NAME = os.getenv('SENDER_NAME', 'QuizMaster Admin')
