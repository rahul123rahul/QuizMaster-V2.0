import os
import re
import urllib.parse
from dotenv import load_dotenv

load_dotenv()

# ==============================================================================
# POSTGRESQL / SUPABASE COMPATIBILITY WRAPPER
# ==============================================================================
class PostgresCursorWrapper:
    """
    Wraps psycopg2 RealDictCursor to provide MySQL-compatible interface
    (Dict-like results, cursor.lastrowid on INSERT, rowcount, context manager).
    """
    def __init__(self, raw_cursor, raw_conn):
        self._cur = raw_cursor
        self._conn = raw_conn
        self._last_id = None

    def execute(self, query, params=None):
        res = self._cur.execute(query, params)
        q_upper = query.strip().upper()
        if q_upper.startswith("INSERT"):
            try:
                with self._conn.cursor() as seq_cur:
                    seq_cur.execute("SELECT LASTVAL()")
                    row = seq_cur.fetchone()
                    if row:
                        self._last_id = row[0]
            except Exception:
                self._last_id = None
        else:
            self._last_id = None
        return res

    def executemany(self, query, seq_of_params):
        return self._cur.executemany(query, seq_of_params)

    def fetchone(self):
        r = self._cur.fetchone()
        return dict(r) if r is not None else None

    def fetchall(self):
        rows = self._cur.fetchall()
        return [dict(r) for r in rows] if rows else []

    def fetchmany(self, size=None):
        rows = self._cur.fetchmany(size)
        return [dict(r) for r in rows] if rows else []

    @property
    def lastrowid(self):
        return self._last_id

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def close(self):
        return self._cur.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._cur.close()

class PostgresConnectionWrapper:
    """
    Wraps psycopg2 connection to mimic PyMySQL interface with autocommit.
    """
    def __init__(self, raw_conn):
        self._conn = raw_conn
        self._conn.autocommit = True

    def cursor(self, *args, **kwargs):
        try:
            from psycopg2.extras import RealDictCursor
            raw_cur = self._conn.cursor(cursor_factory=RealDictCursor)
        except ImportError:
            raw_cur = self._conn.cursor()
        return PostgresCursorWrapper(raw_cur, self._conn)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

def is_postgres_configured():
    """Detects whether PostgreSQL / Supabase credentials are provided."""
    db_url = os.getenv('DATABASE_URL', '') or os.getenv('SUPABASE_DB_URL', '')
    if db_url.startswith('postgres://') or db_url.startswith('postgresql://'):
        return True
    db_type = os.getenv('DB_TYPE', '').lower()
    if db_type in ('postgres', 'postgresql', 'supabase'):
        return True
    port = str(os.getenv('DB_PORT', '3306'))
    host = os.getenv('DB_HOST', '').lower()
    return port in ('5432', '6543') or 'supabase.co' in host

# ==============================================================================
# DATABASE CONNECTION FACTORY (DUAL: MySQL & PostgreSQL / Supabase)
# ==============================================================================
def get_db_connection():
    """
    Establishes and returns a connection to:
    1. Supabase / PostgreSQL (if DATABASE_URL, port 5432, or supabase host configured)
    2. MySQL / MariaDB (default if host is localhost or port 3306)
    """
    if is_postgres_configured():
        return _get_postgres_connection()
    return _get_mysql_connection()

def _get_postgres_connection():
    try:
        import psycopg2
    except ImportError:
        print("[ERROR] psycopg2 is not installed. Please run: pip install psycopg2-binary")
        return None

    db_url = os.getenv('DATABASE_URL', '') or os.getenv('SUPABASE_DB_URL', '')
    
    try:
        if db_url:
            # Handle special characters (like @ in password) if raw URI is provided
            conn = psycopg2.connect(db_url, connect_timeout=15)
        else:
            conn = psycopg2.connect(
                host=os.getenv('DB_HOST', 'localhost'),
                port=int(os.getenv('DB_PORT', '5432')),
                dbname=os.getenv('DB_NAME', 'postgres'),
                user=os.getenv('DB_USER', 'postgres'),
                password=os.getenv('DB_PASSWORD', ''),
                connect_timeout=15
            )
        return PostgresConnectionWrapper(conn)
    except Exception as e:
        print(f"[ERROR] PostgreSQL/Supabase database connection failed: {e}")
        return None

def _get_mysql_connection():
    try:
        import pymysql
        import pymysql.cursors
    except ImportError:
        print("[ERROR] pymysql is not installed. Please run: pip install pymysql")
        return None

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
    except Exception as e:
        print(f"[ERROR] MySQL database connection failed: {e}")
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
            if row and (row.get('alive') == 1 or row.get('alive') is not None):
                latency_ms = round((time.time() - start) * 1000, 2)
                engine = "Supabase PostgreSQL" if is_postgres_configured() else "MySQL"
                return True, f"Database ({engine}) healthy (ping: {latency_ms}ms)"
        return False, "Unexpected ping query result."
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

# 2. EMAIL CONFIGURATION (BREVO API)
BREVO_API_KEY = os.getenv('BREVO_API_KEY', '')
SENDER_EMAIL = os.getenv('SENDER_EMAIL', 'asr082239@gmail.com')
SENDER_NAME = os.getenv('SENDER_NAME', 'QuizMaster Admin')
