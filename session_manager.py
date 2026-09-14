import time
import secrets
import threading
from database import get_db_connection

# Configurable timeout: 25 minutes as requested
INACTIVITY_TIMEOUT_SECONDS = 25 * 60  # 1500 seconds

# Thread-safe in-memory cache for fast session token verification
_LOCK = threading.Lock()
_ACTIVE_SESSIONS = {}  # {user_id: session_token}
_DB_COLUMN_CHECKED = False

def ensure_session_columns():
    """Ensures the Users table has active_session_token and last_activity columns."""
    global _DB_COLUMN_CHECKED
    if _DB_COLUMN_CHECKED:
        return
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                try:
                    cursor.execute("ALTER TABLE Users ADD COLUMN active_session_token VARCHAR(64)")
                except Exception:
                    pass
                try:
                    cursor.execute("ALTER TABLE Users ADD COLUMN last_active_time DATETIME")
                except Exception:
                    pass
            conn.commit()
            _DB_COLUMN_CHECKED = True
        except Exception as e:
            print(f"Notice: Column check exception: {e}")
        finally:
            conn.close()

def register_user_session(user_id, role):
    """
    Generates a new session token for the user, stores it in-memory and in DB.
    Any existing session for this user will be superseded (single-device enforcement).
    """
    token = secrets.token_hex(24)
    with _LOCK:
        _ACTIVE_SESSIONS[user_id] = token

    # Persist to DB if connected
    ensure_session_columns()
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE Users 
                    SET active_session_token=%s, last_active_time=NOW() 
                    WHERE user_id=%s
                """, (token, user_id))
            conn.commit()
        except Exception as e:
            print(f"Notice: Failed to update active_session_token in DB: {e}")
        finally:
            conn.close()

    return token

def get_active_user_token(user_id):
    """Retrieves the latest valid session token for this user."""
    with _LOCK:
        token = _ACTIVE_SESSIONS.get(user_id)
        if token:
            return token

    # Fallback to database if server restarted
    ensure_session_columns()
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT active_session_token FROM Users WHERE user_id=%s", (user_id,))
                row = cursor.fetchone()
                if row and row.get('active_session_token'):
                    token = row['active_session_token']
                    with _LOCK:
                        _ACTIVE_SESSIONS[user_id] = token
                    return token
        except Exception:
            pass
        finally:
            conn.close()

    return None

def validate_user_session(user_id, session_token):
    """
    Returns True if session_token matches the current active token for user_id.
    Returns False if user has logged in from another device/browser or has been logged out.
    """
    if not user_id or not session_token:
        return False
    active_token = get_active_user_token(user_id)
    if not active_token:
        return False
    return active_token == session_token

def invalidate_user_session(user_id):
    """Clears the active session token upon explicit logout."""
    if not user_id:
        return
    with _LOCK:
        _ACTIVE_SESSIONS[user_id] = ""  # Cleared / invalidated sentinel

    ensure_session_columns()
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE Users SET active_session_token=NULL WHERE user_id=%s", (user_id,))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()


def has_active_exam_session(user_id):
    """
    Checks if a student currently has an In-Progress exam attempt.
    If yes, they are in an active examination and should not be timed out.
    """
    if not user_id:
        return False
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT attempt_id FROM Quiz_Attempts 
                    WHERE user_id=%s AND (status='In-Progress' OR status='In Progress' OR status='in_progress')
                    ORDER BY attempt_id DESC LIMIT 1
                """, (user_id,))
                row = cursor.fetchone()
                return bool(row)
        except Exception:
            return False
        finally:
            conn.close()
    return False

def is_inactive(last_activity_time):
    """
    Returns True if last_activity_time was more than INACTIVITY_TIMEOUT_SECONDS (25 mins) ago.
    """
    if not last_activity_time:
        return False
    try:
        elapsed = time.time() - float(last_activity_time)
        return elapsed > INACTIVITY_TIMEOUT_SECONDS
    except Exception:
        return False
