import os
import sys
import json
from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db_connection, ping_db

def validate_and_cleanup_database():
    print("==================================================")
    print("QUIZMASTER PRODUCTION DATABASE VALIDATION & CLEANUP")
    print("==================================================")

    # 1. Ping test
    healthy, msg = ping_db()
    if not healthy:
        print(f"[FAIL] Database connectivity issue: {msg}")
        return False
    print(f"[OK] Database connection verified: {msg}")

    conn = get_db_connection()
    if not conn:
        print("[FAIL] Could not get database connection.")
        return False

    try:
        with conn.cursor() as cursor:
            # 2. PASSWORD HASHING MIGRATION
            print("\n--- Phase 1: Security Audit & Password Hashing ---")
            cursor.execute("SELECT user_id, email, password_hash, full_name, role FROM Users")
            users = cursor.fetchall()
            migrated_count = 0
            for u in users:
                ph = u.get('password_hash') or ''
                if not ph.startswith(('scrypt:', 'pbkdf2:')):
                    # Plaintext password detected! Upgrade to Werkzeug salted hash
                    hashed = generate_password_hash(ph)
                    cursor.execute("UPDATE Users SET password_hash=%s WHERE user_id=%s", (hashed, u['user_id']))
                    migrated_count += 1
                    print(f"  [UPGRADED] User {u['email']} ({u['role']}) plaintext password converted to salted Werkzeug hash.")

            # Update default admin name if still 'Test User'
            cursor.execute("SELECT user_id, full_name FROM Users WHERE role='Admin' AND email='admin@quiz.com'")
            admin_user = cursor.fetchone()
            if admin_user and admin_user.get('full_name') == 'Test User':
                cursor.execute("UPDATE Users SET full_name='System Administrator' WHERE user_id=%s", (admin_user['user_id'],))
                print("  [UPDATED] Admin account full name updated to 'System Administrator'.")

            if migrated_count == 0:
                print("  [OK] All existing accounts already have secure password hashes.")

            # 3. MOCK / DUMMY DATA CLEANUP
            print("\n--- Phase 2: Mock & Development Data Cleanup ---")

            # Remove empty dummy quiz named 'test' (quiz_id=3) and any associated test responses/attempts
            cursor.execute("SELECT quiz_id FROM Quizzes WHERE title='test' OR title='Test Quiz'")
            test_quizzes = cursor.fetchall()
            for tq in test_quizzes:
                qid = tq['quiz_id']
                cursor.execute("DELETE FROM Quiz_Responses WHERE attempt_id IN (SELECT attempt_id FROM Quiz_Attempts WHERE quiz_id=%s)", (qid,))
                cursor.execute("DELETE FROM Quiz_Attempts WHERE quiz_id=%s", (qid,))
                cursor.execute("DELETE FROM Questions WHERE quiz_id=%s", (qid,))
                cursor.execute("DELETE FROM Quizzes WHERE quiz_id=%s", (qid,))
                print(f"  [CLEANED] Removed mock quiz #{qid} ('test') and associated attempts/responses.")

            # Clean stale in-progress/abandoned test attempts from admin (user_id=1)
            cursor.execute("""
                DELETE FROM Quiz_Responses WHERE attempt_id IN (
                    SELECT attempt_id FROM Quiz_Attempts WHERE user_id=1 AND status='In-Progress'
                )
            """)
            cursor.execute("DELETE FROM Quiz_Attempts WHERE user_id=1 AND status='In-Progress'")
            print("  [CLEANED] Cleared abandoned in-progress test attempts for admin.")

            # Clean judge_jobs test rows
            try:
                cursor.execute("TRUNCATE TABLE judge_jobs")
                print("  [CLEANED] Cleared temporary judge_jobs test queue.")
            except Exception:
                cursor.execute("DELETE FROM judge_jobs WHERE 1=1")
                print("  [CLEANED] Cleared judge_jobs rows.")

            # Reset development audit log entries
            try:
                cursor.execute("DELETE FROM audit_logs WHERE details LIKE '%test%' OR user_agent LIKE '%python%'")
                print("  [CLEANED] Cleared automated test log entries from audit_logs.")
            except Exception as e:
                print(f"  [NOTICE] audit_logs cleanup notice: {e}")

            # 4. PLATFORM METRICS RECALIBRATION
            print("\n--- Phase 3: Platform Metrics Sync ---")
            cursor.execute("SELECT COUNT(DISTINCT user_id) as total_students FROM Users WHERE role='Student'")
            total_students = cursor.fetchone()['total_students']

            cursor.execute("SELECT COUNT(*) as total_exams FROM Quiz_Attempts WHERE status='Completed'")
            total_exams = cursor.fetchone()['total_exams']

            cursor.execute("SELECT COUNT(*) as total_quizzes FROM Quizzes")
            total_quizzes = cursor.fetchone()['total_quizzes']

            metrics_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'platform_metrics.json')
            os.makedirs(os.path.dirname(metrics_file), exist_ok=True)

            current_metrics = {'students': 0, 'exams': 0, 'quizzes': 0}
            if os.path.exists(metrics_file):
                try:
                    with open(metrics_file, 'r', encoding='utf-8') as f:
                        current_metrics = json.load(f)
                except Exception:
                    pass

            # Maintain monotonic non-decreasing metric rule
            synced_metrics = {
                'students': max(current_metrics.get('students', 0), total_students),
                'exams': max(current_metrics.get('exams', 0), total_exams),
                'quizzes': max(current_metrics.get('quizzes', 0), total_quizzes)
            }

            with open(metrics_file, 'w', encoding='utf-8') as f:
                json.dump(synced_metrics, f, indent=2)

            print(f"  [SYNCED] Platform metrics calibrated: {synced_metrics}")

            # 5. SCHEMA INTEGRITY & INDEX AUDIT
            print("\n--- Phase 4: Schema Integrity & Index Audit ---")
            cursor.execute("DESCRIBE Users")
            user_cols = {c['Field'] for c in cursor.fetchall()}
            required_user_cols = [
                'user_id', 'full_name', 'email', 'password_hash', 'role',
                'must_change_password', 'temporary_password_created_at',
                'password_changed_at', 'created_by', 'created_at',
                'active_session_token', 'last_active_time', 'is_blocked'
            ]
            for col in required_user_cols:
                assert col in user_cols, f"Missing critical column in Users table: {col}"
            print("  [OK] Users table columns validated.")

            cursor.execute("DESCRIBE official_assets")
            asset_cols = {c['Field'] for c in cursor.fetchall()}
            for col in ['id', 'asset_type', 'file_path', 'original_file_name', 'mime_type', 'file_size', 'is_active']:
                assert col in asset_cols, f"Missing column in official_assets table: {col}"
            print("  [OK] official_assets table validated.")

            cursor.execute("DESCRIBE audit_logs")
            audit_cols = {c['Field'] for c in cursor.fetchall()}
            for col in ['audit_id', 'user_id', 'action', 'ip_address', 'details', 'created_at']:
                assert col in audit_cols, f"Missing column in audit_logs table: {col}"
            print("  [OK] audit_logs table validated.")

        conn.commit()
        print("\n==================================================")
        print("DATABASE VALIDATION & CLEANUP COMPLETED SUCCESSFULLY")
        print("==================================================")
        return True

    except Exception as e:
        conn.rollback()
        import traceback
        print(f"\n[FAIL] Error during database cleanup: {e}\n{traceback.format_exc()}")
        return False
    finally:
        conn.close()

if __name__ == '__main__':
    success = validate_and_cleanup_database()
    sys.exit(0 if success else 1)
