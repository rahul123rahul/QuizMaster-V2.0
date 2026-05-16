import pymysql
# Check if database.py exists before importing
try:
    from database import DB_CONFIG
except ImportError:
    print("❌ ERROR: database.py not found in this folder!")
    exit()

print("\n--- DIAGNOSTIC START ---")
print(f"Testing connection to: {DB_CONFIG.get('host')}")
print(f"Using User: {DB_CONFIG.get('user')}")

try:
    conn = pymysql.connect(**DB_CONFIG)
    print("✅ SUCCESS: Password and Host are CORRECT!")
    
    with conn.cursor() as cursor:
        cursor.execute("SHOW TABLES;")
        tables = cursor.fetchall()
        if not tables:
            print("⚠️  WARNING: Database connected, but it is EMPTY (0 tables).")
            print("👉 SOLUTION: You need to run the CREATE TABLE SQL commands.")
        else:
            print(f"✅ TABLES FOUND: {len(tables)} tables exist.")
            
    conn.close()
except Exception as e:
    print("\n❌ CONNECTION FAILED!")
    print(f"Error Message: {e}")
    code = e.args[0] if len(e.args) > 0 else 0
    if code == 1045:
        print("👉 FIX: Your PASSWORD in database.py is wrong.")
    elif code == 2003:
        print("👉 FIX: Your HOST in database.py is wrong (still localhost?).")
    elif code == 1049:
        print("👉 FIX: Your DATABASE NAME in database.py is wrong.")
print("--- DIAGNOSTIC END ---\n")
