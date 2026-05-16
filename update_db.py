import pymysql
from database import get_db_connection

print("Connecting to database...")
conn = get_db_connection()
try:
    with conn.cursor() as cursor:
        print("Checking Users table...")
        try:
            cursor.execute("ALTER TABLE Users ADD COLUMN section VARCHAR(20)")
            print("✅ Added 'section' column to Users.")
        except Exception as e:
            if "Duplicate column" in str(e): print("ℹ️  'section' column already exists in Users.")
            else: print(f"❌ Error Users: {e}")

        print("Checking Quizzes table...")
        try:
            cursor.execute("ALTER TABLE Quizzes ADD COLUMN section VARCHAR(50)")
            print("✅ Added 'section' column to Quizzes.")
        except Exception as e:
            if "Duplicate column" in str(e): print("ℹ️  'section' column already exists in Quizzes.")
            else: print(f"❌ Error Quizzes: {e}")
    conn.commit()
    print("\nDatabase update complete! Restart your app.")
finally:
    conn.close()
