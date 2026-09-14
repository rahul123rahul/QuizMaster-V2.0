import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db_connection

def run_migration():
    conn = get_db_connection()
    if not conn:
        print("ERROR: Could not connect to database")
        return False

    try:
        with conn.cursor() as cursor:
            # 1. Create official_assets table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS official_assets (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    asset_type ENUM('program_director_signature', 'official_seal') NOT NULL,
                    file_path VARCHAR(255) NOT NULL,
                    original_file_name VARCHAR(255) NOT NULL,
                    mime_type VARCHAR(100) NOT NULL,
                    file_size INT NOT NULL,
                    is_active TINYINT(1) DEFAULT 0,
                    uploaded_by INT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_asset_type_active (asset_type, is_active)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            print("Verified/Created table: official_assets")

            # 2. Check and add columns to Users table
            cursor.execute("DESCRIBE Users")
            existing_cols = {row['Field'] for row in cursor.fetchall()}

            cols_to_add = [
                ('must_change_password', 'TINYINT(1) DEFAULT 0'),
                ('temporary_password_created_at', 'DATETIME NULL'),
                ('password_changed_at', 'DATETIME NULL'),
                ('created_by', 'INT NULL'),
                ('created_at', 'DATETIME DEFAULT CURRENT_TIMESTAMP')
            ]

            for col_name, col_def in cols_to_add:
                if col_name not in existing_cols:
                    cursor.execute(f"ALTER TABLE Users ADD COLUMN {col_name} {col_def}")
                    print(f"Added column Users.{col_name}")
                else:
                    print(f"Column Users.{col_name} already exists")

            # 3. Verify audit_logs table exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    audit_id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NULL,
                    action VARCHAR(128) NOT NULL,
                    ip_address VARCHAR(64) NULL,
                    user_agent VARCHAR(255) NULL,
                    details TEXT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_audit_user (user_id),
                    INDEX idx_audit_action (action)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            print("Verified/Created table: audit_logs")

        conn.commit()
        print("Migration completed successfully!")
        return True
    except Exception as e:
        conn.rollback()
        print(f"Migration error: {e}")
        return False
    finally:
        conn.close()

if __name__ == '__main__':
    success = run_migration()
    sys.exit(0 if success else 1)
