import os
import re
import urllib.parse
import datetime
from dotenv import load_dotenv

load_dotenv()

def _sanitize_pg_row(r):
    if r is None:
        return None
    d = dict(r)
    for k, v in d.items():
        if isinstance(v, datetime.datetime) and v.tzinfo is not None:
            d[k] = v.replace(tzinfo=None)
    return d

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
        return _sanitize_pg_row(r)

    def fetchall(self):
        rows = self._cur.fetchall()
        return [_sanitize_pg_row(r) for r in rows] if rows else []

    def fetchmany(self, size=None):
        rows = self._cur.fetchmany(size)
        return [_sanitize_pg_row(r) for r in rows] if rows else []

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

_LAST_CONNECTION_ERROR = None
_PG_FUNCS_ENSURED = False

def _ensure_postgres_compatibility_functions(raw_conn):
    global _PG_FUNCS_ENSURED
    if _PG_FUNCS_ENSURED:
        return
    try:
        with raw_conn.cursor() as cur:
            cur.execute("""
            CREATE OR REPLACE FUNCTION find_in_set(str text, strlist text)
            RETURNS integer AS $$
            DECLARE
                pos integer;
                arr text[];
            BEGIN
                IF str IS NULL OR strlist IS NULL THEN
                    RETURN 0;
                END IF;
                arr := string_to_array(strlist, ',');
                IF arr IS NULL THEN
                    RETURN 0;
                END IF;
                FOR pos IN 1..COALESCE(array_length(arr, 1), 0) LOOP
                    IF trim(arr[pos]) = trim(str) THEN
                        RETURN pos;
                    END IF;
                END LOOP;
                RETURN 0;
            END;
            $$ LANGUAGE plpgsql IMMUTABLE;
            """)
            raw_conn.commit()
            _PG_FUNCS_ENSURED = True
    except Exception:
        try:
            raw_conn.rollback()
        except Exception:
            pass

def is_postgres_configured():
    """Detects whether PostgreSQL / Supabase credentials are provided."""
    for key in ('DATABASE_URL', 'POSTGRES_URL', 'SUPABASE_DB_URL'):
        val = os.getenv(key, '').strip()
        if val.startswith('postgres://') or val.startswith('postgresql://'):
            return True
    db_type = os.getenv('DB_TYPE', '').lower()
    if db_type in ('postgres', 'postgresql', 'supabase'):
        return True
    port = str(os.getenv('DB_PORT', '3306'))
    host = os.getenv('DB_HOST', '').lower()
    return port in ('5432', '6543') or 'supabase.co' in host

def _parse_postgres_url(raw_url):
    """
    Safely parses PostgreSQL connection URIs, including passwords with unescaped '@' symbols.
    """
    if not raw_url:
        return None
    raw_url = raw_url.strip()
    m = re.match(r'^(?:postgresql|postgres)://([^:]+):(.+)@([^:/@]+)(?::(\d+))?/(.+)$', raw_url)
    if m:
        u, p, h, port, db = m.groups()
        return {
            'user': urllib.parse.unquote(u),
            'password': urllib.parse.unquote(p),
            'host': h,
            'port': int(port) if port else 5432,
            'dbname': db.split('?')[0]
        }
    return None

# ==============================================================================
# DATABASE CONNECTION FACTORY (DUAL: MySQL & PostgreSQL / Supabase)
# ==============================================================================
def get_db_connection():
    """
    Establishes and returns a connection to:
    1. Supabase / PostgreSQL (if DATABASE_URL, port 5432, or supabase host configured)
    2. MySQL / MariaDB (default if host is localhost or port 3306)
    """
    global _LAST_CONNECTION_ERROR
    _LAST_CONNECTION_ERROR = None

    if is_postgres_configured():
        return _get_postgres_connection()
    return _get_mysql_connection()

def _get_postgres_connection():
    global _LAST_CONNECTION_ERROR
    try:
        import psycopg2
    except ImportError as e:
        _LAST_CONNECTION_ERROR = "psycopg2 is not installed. Please add psycopg2-binary to requirements.txt"
        print(f"[ERROR] {_LAST_CONNECTION_ERROR}")
        return None

    db_url = os.getenv('DATABASE_URL', '') or os.getenv('POSTGRES_URL', '') or os.getenv('SUPABASE_DB_URL', '')
    
    try:
        if db_url:
            parsed = _parse_postgres_url(db_url)
            if parsed:
                conn = psycopg2.connect(
                    host=parsed['host'],
                    port=parsed['port'],
                    dbname=parsed['dbname'],
                    user=parsed['user'],
                    password=parsed['password'],
                    sslmode='require',
                    connect_timeout=15
                )
            else:
                conn = psycopg2.connect(db_url, sslmode='require', connect_timeout=15)
        else:
            host = os.getenv('DB_HOST', 'localhost')
            port = int(os.getenv('DB_PORT', '5432'))
            dbname = os.getenv('DB_NAME', 'postgres')
            user = os.getenv('DB_USER', 'postgres')
            password = os.getenv('DB_PASSWORD', '')
            
            conn = psycopg2.connect(
                host=host,
                port=port,
                dbname=dbname,
                user=user,
                password=password,
                sslmode='require' if 'supabase.co' in host.lower() else 'prefer',
                connect_timeout=15
            )
        _ensure_postgres_compatibility_functions(conn)
        return PostgresConnectionWrapper(conn)
    except Exception as e:
        _LAST_CONNECTION_ERROR = str(e)
        print(f"[ERROR] PostgreSQL/Supabase database connection failed: {e}")
        return None

def _get_mysql_connection():
    global _LAST_CONNECTION_ERROR
    try:
        import pymysql
        import pymysql.cursors
    except ImportError as e:
        _LAST_CONNECTION_ERROR = "pymysql is not installed."
        print(f"[ERROR] {_LAST_CONNECTION_ERROR}")
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
        _LAST_CONNECTION_ERROR = str(e)
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
        err = _LAST_CONNECTION_ERROR or "Check database environment variables."
        return False, f"Connection failed: {err}"
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
        return False, f"Query error: {e}"
    finally:
        conn.close()


# 2. EMAIL CONFIGURATION (BREVO API)
BREVO_API_KEY = os.getenv('BREVO_API_KEY', '')
SENDER_EMAIL = os.getenv('SENDER_EMAIL', 'asr082239@gmail.com')
SENDER_NAME = os.getenv('SENDER_NAME', 'QuizMaster Admin')
