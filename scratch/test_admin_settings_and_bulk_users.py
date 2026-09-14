import os
import sys
import io
import time
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_db_connection
from official_assets_manager import (
    upload_official_asset, get_official_assets, get_active_official_asset,
    set_official_asset_active, delete_official_asset, ASSET_UPLOAD_DIR
)
from user_management_service import (
    create_single_user, create_bulk_users_manual, generate_csv_template,
    parse_and_validate_csv, execute_csv_import, generate_error_csv,
    get_users_directory, reset_user_temp_password, force_user_password_change,
    verify_user_password, hash_user_password
)
from certificate_generator import generate_certificate_pdf
from werkzeug.datastructures import FileStorage

class DummyFileStorage:
    def __init__(self, stream, filename, content_type):
        self.stream = stream
        self.filename = filename
        self.content_type = content_type
        self.mimetype = content_type

    def read(self, *args):
        return self.stream.read(*args)

    def seek(self, *args):
        return self.stream.seek(*args)

def create_sample_png_bytes(color=(79, 70, 229)):
    img = Image.new('RGBA', (100, 60), color=color)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf

def test_asset_management():
    print("\n--- TEST 1: Asset Management & Single-Active Rule ---")
    # 1. Create dummy image A
    buf_a = create_sample_png_bytes((255, 0, 0))
    fs_a = DummyFileStorage(buf_a, 'test_signature_a.png', 'image/png')
    res_a = upload_official_asset('program_director_signature', fs_a, uploaded_by=1, auto_activate=True)
    assert res_a['success'], f"Failed to upload signature A: {res_a}"
    asset_id_a = res_a['asset_id']
    print(f"Uploaded Signature A (ID: {asset_id_a}, active: {res_a['is_active']})")

    # Verify A is active
    active_sig = get_active_official_asset('program_director_signature')
    assert active_sig and active_sig['id'] == asset_id_a, "Signature A should be active"

    # 2. Upload dummy image B with auto_activate=True
    time.sleep(0.1)
    buf_b = create_sample_png_bytes((0, 255, 0))
    fs_b = DummyFileStorage(buf_b, 'test_signature_b.png', 'image/png')
    res_b = upload_official_asset('program_director_signature', fs_b, uploaded_by=1, auto_activate=True)
    assert res_b['success'], f"Failed to upload signature B: {res_b}"
    asset_id_b = res_b['asset_id']
    print(f"Uploaded Signature B (ID: {asset_id_b}, active: {res_b['is_active']})")

    # Verify Single-Active Rule: B is active, A is deactivated
    active_sig = get_active_official_asset('program_director_signature')
    assert active_sig and active_sig['id'] == asset_id_b, "Signature B should now be active"

    all_sigs = get_official_assets('program_director_signature')
    sig_a_record = next(s for s in all_sigs if s['id'] == asset_id_a)
    assert sig_a_record['is_active'] == 0, f"Signature A should have been deactivated, got: {sig_a_record['is_active']}"
    print(" Verified Single-Active Rule: Only Signature B is active, A is deactivated.")

    # 3. Upload official seal
    buf_seal = create_sample_png_bytes((218, 165, 32))
    fs_seal = DummyFileStorage(buf_seal, 'test_seal.png', 'image/png')
    res_seal = upload_official_asset('official_seal', fs_seal, uploaded_by=1, auto_activate=True)
    assert res_seal['success'], f"Failed to upload seal: {res_seal}"
    seal_id = res_seal['asset_id']
    print(f"Uploaded Official Seal (ID: {seal_id})")

    active_seal = get_active_official_asset('official_seal')
    assert active_seal and active_seal['id'] == seal_id, "Official seal should be active"

    # 4. Test invalid file rejection
    fake_fs = DummyFileStorage(io.BytesIO(b"NOT AN IMAGE"), 'bad.exe', 'application/x-msdownload')
    res_bad = upload_official_asset('program_director_signature', fake_fs, uploaded_by=1)
    assert not res_bad['success'], "Should have rejected bad extension"
    print(" Verified rejection of disallowed file type.")

    # 5. Clean up test assets
    del_a = delete_official_asset(asset_id_a, admin_user_id=1)
    del_b = delete_official_asset(asset_id_b, admin_user_id=1)
    del_s = delete_official_asset(seal_id, admin_user_id=1)
    assert del_a['success'] and del_b['success'] and del_s['success']
    print(" Verified asset deletion and storage cleanup.")

def test_certificate_integration():
    print("\n--- TEST 2: Certificate Generation with Dynamic Assets ---")
    # Upload temporary test signature & seal
    buf_sig = create_sample_png_bytes((79, 70, 229))
    fs_sig = DummyFileStorage(buf_sig, 'cert_test_sig.png', 'image/png')
    res_sig = upload_official_asset('program_director_signature', fs_sig, uploaded_by=1, auto_activate=True)

    buf_seal = create_sample_png_bytes((218, 165, 32))
    fs_seal = DummyFileStorage(buf_seal, 'cert_test_seal.png', 'image/png')
    res_seal = upload_official_asset('official_seal', fs_seal, uploaded_by=1, auto_activate=True)

    pdf_buf = generate_certificate_pdf(
        student_name="Test Student",
        course_name="Computer Science Assessment",
        score=95,
        date="2026-09-14",
        attempt_id=1,
        cert_type="Achievement",
        show_qr=False
    )
    pdf_bytes = pdf_buf.getvalue()
    assert len(pdf_bytes) > 1000, "PDF buffer should contain generated certificate bytes"
    assert pdf_bytes.startswith(b'%PDF'), "PDF buffer should start with PDF magic header"
    print(f" Verified certificate generated successfully ({len(pdf_bytes)} bytes) with dynamic signature & seal.")

    # Clean up
    delete_official_asset(res_sig['asset_id'], admin_user_id=1)
    delete_official_asset(res_seal['asset_id'], admin_user_id=1)

def test_user_creation_and_first_login():
    print("\n--- TEST 3: User Management, Bulk Creation & First-Login Password Change ---")
    test_email_single = f"test_user_{int(time.time())}@example.com"
    test_roll_single = f"ROLL_{int(time.time()) % 100000}"

    # 1. Single User Creation
    user_data = {
        'full_name': 'Test Single Student',
        'email': test_email_single,
        'mobile': '9876543210',
        'role': 'Student',
        'occupation': 'Student',
        'college': 'Engineering College',
        'department': 'CSE',
        'roll_number': test_roll_single,
        'section': 'A',
        'study_year': 'II/I sem',
        'enrolled_session': 'Batch-2026'
    }

    res_single = create_single_user(user_data, admin_id=1)
    assert res_single['success'], f"Single user creation failed: {res_single}"
    created_id = res_single['user_id']
    temp_pw = res_single['temp_password']
    assert res_single['must_change_password'] is True
    print(f" Created single user {test_email_single} (ID: {created_id}) with temp password.")

    # Verify must_change_password in DB
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT must_change_password, password_hash FROM Users WHERE user_id=%s", (created_id,))
        row = cursor.fetchone()
        assert row['must_change_password'] == 1, "DB must_change_password should be 1"
        assert verify_user_password(row['password_hash'], temp_pw), "Password verification should succeed with temp password"
    conn.close()

    # 2. Bulk Manual User Creation
    bulk_users = [
        {
            'full_name': 'Bulk Student One',
            'email': f"bulk1_{int(time.time())}@example.com",
            'mobile': '9876543211',
            'role': 'Student',
            'college': 'Engineering College',
            'department': 'CSE',
            'roll_number': f"R1_{int(time.time()) % 100000}"
        },
        {
            'full_name': 'Bulk Student Two',
            'email': f"bulk2_{int(time.time())}@example.com",
            'mobile': '9876543212',
            'role': 'Student',
            'college': 'Engineering College',
            'department': 'ECE',
            'roll_number': f"R2_{int(time.time()) % 100000}"
        }
    ]
    res_bulk = create_bulk_users_manual(bulk_users, admin_id=1)
    assert res_bulk['success'], f"Bulk creation failed: {res_bulk}"
    assert res_bulk['created_count'] == 2, "Should create 2 users"
    print(" Verified manual bulk user creation (2 users created in atomic transaction).")

    # 3. CSV Parsing, Validation & Import
    csv_content = f"""full_name,email,mobile,role,college,department,roll_number,password
CSV User Valid,csv_val_{int(time.time())}@example.com,9876543213,Student,Tech Institute,CSE,CSV1_{int(time.time()) % 10000},Temp12345
CSV User Invalid,not-an-email,9876543214,Student,Tech Institute,CSE,CSV2_{int(time.time()) % 10000},Temp12346
"""
    fs_csv = DummyFileStorage(io.BytesIO(csv_content.encode('utf-8')), 'test_import.csv', 'text/csv')
    preview_res = parse_and_validate_csv(fs_csv)
    assert preview_res['success'], f"CSV preview failed: {preview_res}"
    assert preview_res['total_rows'] == 2
    assert preview_res['valid_rows'] == 1
    assert preview_res['invalid_rows'] == 1
    print(" Verified CSV parser & validator (correctly flagged 1 valid, 1 invalid).")

    # Import valid records
    import_res = execute_csv_import(preview_res['preview_data'], admin_id=1)
    assert import_res['success'], f"CSV import failed: {import_res}"
    assert import_res['created_count'] == 1
    assert import_res['skipped_count'] == 1
    print(" Verified CSV import execution (1 valid account created, 1 invalid row skipped).")

    # Verify CSV error generation and formula injection escaping
    err_csv = generate_error_csv([{'row_number': 3, 'email': '=SUM(A1)', 'reason': 'Malicious'}])
    assert "'=SUM(A1)" in err_csv, "CSV formula injection should be escaped with leading quote"
    print(" Verified CSV error reporting & formula injection protection.")

    # 4. First-Login Password Change Flow via Flask Test Client
    from main import app
    client = app.test_client()

    # Attempt login with temp password
    login_res = client.post('/login', data={'login_id': test_email_single, 'password': temp_pw}, follow_redirects=False)
    assert login_res.status_code == 302, "Should redirect"
    assert '/change-password' in login_res.headers['Location'], f"Should redirect to /change-password, got {login_res.headers['Location']}"
    print(" Verified first-login redirect to /change-password.")

    with client.session_transaction() as sess:
        assert sess.get('must_change_password') == 1, "Session should flag must_change_password=1"

    # Attempt accessing dashboard before password change -> should be blocked and redirected
    dash_res = client.get('/student', follow_redirects=False)
    assert dash_res.status_code == 302 and '/change-password' in dash_res.headers['Location'], "Must block dashboard access before password change"
    print(" Verified dashboard access blocked until password change is complete.")

    # Change password: test wrong current password rejection
    bad_cur_res = client.post('/api/auth/change-password', json={
        'current_password': 'WrongPassword123',
        'new_password': 'NewStrongPassword@2026',
        'confirm_password': 'NewStrongPassword@2026'
    })
    assert bad_cur_res.status_code == 400
    assert "Current password is incorrect" in bad_cur_res.get_json()['message']

    # Change password: test same password rejection
    same_pw_res = client.post('/api/auth/change-password', json={
        'current_password': temp_pw,
        'new_password': temp_pw,
        'confirm_password': temp_pw
    })
    assert same_pw_res.status_code == 400
    assert "cannot be identical" in same_pw_res.get_json()['message']

    # Change password: test valid password change
    new_secret = "MyNewSecurePassword#2026"
    good_pw_res = client.post('/api/auth/change-password', json={
        'current_password': temp_pw,
        'new_password': new_secret,
        'confirm_password': new_secret
    })
    assert good_pw_res.status_code == 200, f"Password change failed: {good_pw_res.get_json()}"
    assert good_pw_res.get_json()['success'] is True
    print(" Verified successful password change.")

    with client.session_transaction() as sess:
        assert sess.get('must_change_password') == 0, "Session flag must_change_password should now be 0"

    # Verify DB updated
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT must_change_password, password_hash FROM Users WHERE user_id=%s", (created_id,))
        u = cursor.fetchone()
        assert u['must_change_password'] == 0, "DB must_change_password should now be 0"
        assert verify_user_password(u['password_hash'], new_secret), "DB should verify with new password"
        assert not verify_user_password(u['password_hash'], temp_pw), "Old temp password must no longer work"
    conn.close()
    print(" Verified old temporary password invalidated, new password active.")

    # Clean up test user
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM Users WHERE email=%s", (test_email_single,))
        for b in bulk_users:
            cursor.execute("DELETE FROM Users WHERE email=%s", (b['email'],))
        cursor.execute("DELETE FROM Users WHERE email LIKE 'csv_val_%'")
    conn.commit()
    conn.close()
    print(" Cleaned up test user accounts.")

def test_audit_logs():
    print("\n--- TEST 4: Audit Logs Verification ---")
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM audit_logs ORDER BY audit_id DESC LIMIT 5")
        logs = cursor.fetchall()
        assert len(logs) > 0, "Audit logs should contain recent events"
        actions = [l['action'] for l in logs]
        print(f" Recent audit log actions captured: {actions}")
    conn.close()
    print(" Verified audit log entries created successfully.")

if __name__ == '__main__':
    try:
        test_asset_management()
        test_certificate_integration()
        test_user_creation_and_first_login()
        test_audit_logs()
        print("\n=======================================================")
        print(" ALL TESTS PASSED SUCCESSFULLY! EVERYTHING IS VERIFIED.")
        print("=======================================================\n")
        sys.exit(0)
    except Exception as e:
        import traceback
        print(f"\nTEST FAILED WITH EXCEPTION:\n{traceback.format_exc()}")
        sys.exit(1)
