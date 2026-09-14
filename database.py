import os
import pymysql
import pymysql.err

# 1. DATABASE CONNECTION
def get_db_connection():
    """
    Establishes and returns a connection to MySQL/MariaDB database.
    Configured with utf8mb4 charset and robust connection handling.
    """
    ssl_config = None
    ssl_ca = os.getenv('DB_SSL_CA')
    if ssl_ca and os.path.exists(ssl_ca):
        ssl_config = {'ca': ssl_ca}

    try:
        connection = pymysql.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            user=os.getenv('DB_USER', 'root'),
            password=os.getenv('DB_PASSWORD', ''),
            database=os.getenv('DB_NAME', 'qcms_db'),
            port=int(os.getenv('DB_PORT', '3306')),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            charset='utf8mb4',
            ssl=ssl_config,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30
        )
        return connection
    except pymysql.MySQLError as e:
        print(f"[ERROR] MySQL database connection failed: {e}")
        return None
    except Exception as e:
        print(f"[ERROR] Unexpected database connection error: {e}")
        return None

def ping_db():
    """
    Health check utility to verify database connectivity and response time.
    Returns (is_healthy, message_or_latency_ms)
    """
    import time
    start = time.time()
    conn = get_db_connection()
    if not conn:
        return False, "Failed to establish database connection."
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 AS alive")
            row = cursor.fetchone()
            if row and row.get('alive') == 1:
                latency_ms = round((time.time() - start) * 1000, 2)
                return True, f"Database healthy (ping: {latency_ms}ms)"
        return False, "Unexpected ping query result."
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

# 2. EMAIL CONFIGURATION (BREVO API)
BREVO_API_KEY = os.getenv('BREVO_API_KEY', '')
SENDER_EMAIL = os.getenv('SENDER_EMAIL', 'asr082239@gmail.com')
SENDER_NAME = os.getenv('SENDER_NAME', 'QuizMaster Admin')
