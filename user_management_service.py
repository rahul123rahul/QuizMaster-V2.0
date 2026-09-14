import os
import io
import re
import csv
import string
import secrets
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_connection
from official_assets_manager import log_admin_action

# Standard Department Options
ALLOWED_DEPARTMENTS = [
    'Civil',
    'Mechanical',
    'CSE',
    'CSE- Artificial Intelligence and Machine Learning',
    'CSE- Cyber Security',
    'CSE- Data Science',
    'AI&DS- Artificial Intelligence and Data Science',
    'ECE'
]

ALLOWED_ROLES = ['Student', 'Coordinator', 'Admin']
ALLOWED_SECTIONS = ['A', 'B', 'C', 'D']
ALLOWED_YEARS = [
    'I/I sem', 'I/II sem',
    'II/I sem', 'II/II sem',
    'III/I sem', 'III/II sem',
    'IV/I sem', 'IV/II sem'
]

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')
MOBILE_REGEX = re.compile(r'^\+?[0-9]{10,15}$')

def sanitize_csv_cell(val):
    """Prevents CSV Formula Injection by prepending single quote to formula trigger characters."""
    if val is None:
        return ''
    s = str(val).strip()
    if s and s[0] in ('=', '+', '-', '@', '\t', '\r'):
        return f"'{s}"
    return s

def generate_temp_password(length=10):
    """Generates a secure, human-readable temporary password."""
    # Ensure at least 1 uppercase, 1 lowercase, 1 digit, 1 special symbol
    letters_upper = string.ascii_uppercase
    letters_lower = string.ascii_lowercase
    digits = string.digits
    special = "@#$!"

    chars = [
        secrets.choice(letters_upper),
        secrets.choice(letters_lower),
        secrets.choice(digits),
        secrets.choice(special)
    ]
    all_chars = letters_upper + letters_lower + digits + special
    for _ in range(length - 4):
        chars.append(secrets.choice(all_chars))
    secrets.SystemRandom().shuffle(chars)
    return ''.join(chars)

def hash_user_password(plain_password):
    """Hashes password with Werkzeug's secure hashing algorithm."""
    return generate_password_hash(plain_password)

def verify_user_password(stored_hash, plain_password):
    """
    Verifies user password with backward compatibility.
    Supports Werkzeug hashes (pbkdf2, scrypt) as well as legacy plaintext passwords.
    """
    if not stored_hash or not plain_password:
        return False
    if stored_hash.startswith(('scrypt:', 'pbkdf2:')):
        try:
            return check_password_hash(stored_hash, plain_password)
        except Exception:
            return False
    # Legacy plaintext fallback
    return stored_hash == plain_password

def validate_user_fields(record, existing_emails_set=None, existing_rolls_set=None, db_cursor=None):
    """
    Validates user fields based on QuizMaster registration schema.
    Returns (is_valid, errors_dict, cleaned_record).
    """
    errors = {}
    cleaned = {}

    full_name = str(record.get('full_name', '')).strip()
    email = str(record.get('email', '')).strip().lower()
    mobile = str(record.get('mobile', '') or record.get('mobile_number', '') or record.get('phone_number', '')).strip()
    password = str(record.get('password', '') or record.get('temp_password', '')).strip()
    role = str(record.get('role', 'Student')).strip().capitalize()
    occupation = str(record.get('occupation', 'Student')).strip().capitalize()
    college = str(record.get('college', '') or record.get('college_name', '')).strip()
    department = str(record.get('department', '') or record.get('dept', '')).strip()
    section = str(record.get('section', '')).strip().upper()
    study_year = str(record.get('study_year', '') or record.get('year', '') or record.get('year_sem', '')).strip()
    roll_number = str(record.get('roll_number', '') or record.get('roll_no', '') or record.get('registration_number', '')).strip()
    enrolled_session = str(record.get('enrolled_session', '') or record.get('batch', '') or record.get('session', '')).strip()

    # 1. Full Name
    if not full_name:
        errors['full_name'] = "Full name is required."
    elif len(full_name) < 2:
        errors['full_name'] = "Full name must be at least 2 characters."
    cleaned['full_name'] = full_name

    # 2. Role
    if role not in ALLOWED_ROLES:
        # Default to Student if empty or invalid
        role = 'Student'
    cleaned['role'] = role

    # 3. Email
    if not email:
        errors['email'] = "Email is required."
    elif not EMAIL_REGEX.match(email):
        errors['email'] = "Invalid email format."
    elif existing_emails_set is not None and email in existing_emails_set:
        errors['email'] = "Email duplicated in this submission."
    elif db_cursor:
        db_cursor.execute("SELECT user_id FROM Users WHERE email=%s", (email,))
        if db_cursor.fetchone():
            errors['email'] = "Email already registered in system."
    cleaned['email'] = email

    # 4. Mobile
    if not mobile:
        errors['mobile'] = "Mobile number is required."
    else:
        clean_mob = re.sub(r'[\s\-()]', '', mobile)
        if not MOBILE_REGEX.match(clean_mob):
            errors['mobile'] = "Mobile number must be a valid 10-15 digit number."
        cleaned['mobile'] = clean_mob

    # 5. Password / Temp Password
    if not password:
        password = generate_temp_password()
        cleaned['is_generated_password'] = True
    else:
        if len(password) < 6:
            errors['password'] = "Password must be at least 6 characters."
        cleaned['is_generated_password'] = False
    cleaned['password'] = password

    # 6. Occupation & Student Details
    cleaned['occupation'] = occupation if occupation in ['Student', 'Employee'] else 'Student'
    cleaned['enrolled_session'] = enrolled_session

    if cleaned['role'] == 'Student' or cleaned['occupation'] == 'Student':
        if not college:
            errors['college'] = "College name is required for students."
        cleaned['college'] = college

        if not department:
            errors['department'] = "Department is required for students."
        cleaned['department'] = department

        cleaned['section'] = section if section in ALLOWED_SECTIONS else section
        cleaned['study_year'] = study_year

        if not roll_number:
            errors['roll_number'] = "Roll number is required for students."
        elif existing_rolls_set is not None and roll_number.lower() in existing_rolls_set:
            errors['roll_number'] = "Roll number duplicated in this submission."
        elif db_cursor:
            db_cursor.execute("SELECT user_id FROM Users WHERE roll_number=%s AND roll_number != ''", (roll_number,))
            if db_cursor.fetchone():
                errors['roll_number'] = "Roll number already registered in system."
        cleaned['roll_number'] = roll_number
    else:
        cleaned['college'] = college
        cleaned['department'] = department
        cleaned['section'] = section
        cleaned['study_year'] = study_year
        cleaned['roll_number'] = roll_number

    is_valid = len(errors) == 0
    return is_valid, errors, cleaned

def create_single_user(user_data, admin_id=None, req=None):
    """
    Creates a single user account with must_change_password=1.
    """
    conn = get_db_connection()
    if not conn:
        return {'success': False, 'message': "Database connection unavailable."}

    try:
        with conn.cursor() as cursor:
            is_valid, errors, cleaned = validate_user_fields(user_data, db_cursor=cursor)
            if not is_valid:
                return {'success': False, 'message': "Validation failed.", 'errors': errors}

            pw_hash = hash_user_password(cleaned['password'])
            sql = """
                INSERT INTO Users (
                    full_name, email, mobile, phone_number, password_hash, role,
                    enrolled_session, occupation, college, department, section,
                    study_year, roll_number, must_change_password,
                    temporary_password_created_at, created_by, is_blocked
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, 1,
                    NOW(), %s, 0
                )
            """
            cursor.execute(sql, (
                cleaned['full_name'], cleaned['email'], cleaned['mobile'], cleaned['mobile'],
                pw_hash, cleaned['role'], cleaned['enrolled_session'], cleaned['occupation'],
                cleaned['college'], cleaned['department'], cleaned['section'], cleaned['study_year'],
                cleaned['roll_number'], admin_id
            ))
            new_id = cursor.lastrowid

        conn.commit()

        log_admin_action(
            admin_id,
            'USER_CREATE_SINGLE',
            {'user_id': new_id, 'email': cleaned['email'], 'role': cleaned['role']},
            req
        )

        return {
            'success': True,
            'message': f"User account created for {cleaned['full_name']}.",
            'user_id': new_id,
            'email': cleaned['email'],
            'temp_password': cleaned['password'],
            'must_change_password': True
        }
    except Exception as e:
        conn.rollback()
        return {'success': False, 'message': f"Error creating user: {str(e)}"}
    finally:
        conn.close()

def create_bulk_users_manual(rows, admin_id=None, req=None):
    """
    Creates multiple users submitted manually via the dynamic card/grid UI.
    Performs full batch validation and atomic database transaction.
    """
    if not rows or not isinstance(rows, list):
        return {'success': False, 'message': "No user records provided."}

    conn = get_db_connection()
    if not conn:
        return {'success': False, 'message': "Database connection unavailable."}

    seen_emails = set()
    seen_rolls = set()
    valid_records = []
    row_errors = []

    try:
        with conn.cursor() as cursor:
            for idx, raw_record in enumerate(rows):
                row_num = idx + 1
                is_valid, errors, cleaned = validate_user_fields(
                    raw_record,
                    existing_emails_set=seen_emails,
                    existing_rolls_set=seen_rolls,
                    db_cursor=cursor
                )

                if is_valid:
                    seen_emails.add(cleaned['email'])
                    if cleaned.get('roll_number'):
                        seen_rolls.add(cleaned['roll_number'].lower())
                    valid_records.append((row_num, cleaned))
                else:
                    row_errors.append({
                        'row_number': row_num,
                        'email': raw_record.get('email', ''),
                        'full_name': raw_record.get('full_name', ''),
                        'errors': errors
                    })

            # If there are validation errors, do not insert partially unless configured
            if row_errors:
                return {
                    'success': False,
                    'message': f"Found validation errors in {len(row_errors)} out of {len(rows)} rows. Please resolve all errors.",
                    'valid_count': len(valid_records),
                    'error_count': len(row_errors),
                    'errors': row_errors
                }

            # Insert all valid records within an atomic transaction
            created_summary = []
            insert_sql = """
                INSERT INTO Users (
                    full_name, email, mobile, phone_number, password_hash, role,
                    enrolled_session, occupation, college, department, section,
                    study_year, roll_number, must_change_password,
                    temporary_password_created_at, created_by, is_blocked
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, 1,
                    NOW(), %s, 0
                )
            """

            for row_num, record in valid_records:
                pw_hash = hash_user_password(record['password'])
                cursor.execute(insert_sql, (
                    record['full_name'], record['email'], record['mobile'], record['mobile'],
                    pw_hash, record['role'], record['enrolled_session'], record['occupation'],
                    record['college'], record['department'], record['section'], record['study_year'],
                    record['roll_number'], admin_id
                ))
                uid = cursor.lastrowid
                created_summary.append({
                    'row_number': row_num,
                    'user_id': uid,
                    'full_name': record['full_name'],
                    'email': record['email'],
                    'role': record['role'],
                    'temp_password': record['password']
                })

        conn.commit()

        log_admin_action(
            admin_id,
            'USER_CREATE_BULK_MANUAL',
            {'count': len(created_summary), 'emails': [u['email'] for u in created_summary]},
            req
        )

        return {
            'success': True,
            'message': f"Successfully created {len(created_summary)} user accounts.",
            'created_count': len(created_summary),
            'users': created_summary
        }
    except Exception as e:
        conn.rollback()
        return {'success': False, 'message': f"Transaction failed: {str(e)}"}
    finally:
        conn.close()

def generate_csv_template():
    """Generates a sample CSV template for bulk user import."""
    output = io.StringIO()
    writer = csv.writer(output)
    headers = [
        'full_name', 'email', 'mobile', 'role', 'occupation',
        'college', 'department', 'section', 'year_sem', 'roll_number',
        'enrolled_session', 'password'
    ]
    writer.writerow(headers)
    sample_rows = [
        [
            'Rahul Sharma', 'rahul.sharma@example.com', '9876543210', 'Student', 'Student',
            'College of Engineering', 'CSE', 'A', 'III/I sem', '21CS101',
            'Batch-2026', 'Temp@12345'
        ],
        [
            'Priya Patel', 'priya.patel@example.com', '9876543211', 'Student', 'Student',
            'College of Engineering', 'ECE', 'B', 'II/II sem', '22EC205',
            'Batch-2026', ''
        ],
        [
            'Dr. Amit Verma', 'amit.verma@example.com', '9876543212', 'Coordinator', 'Employee',
            'College of Engineering', 'CSE', '', '', '',
            'Batch-2026', 'Staff@2026'
        ]
    ]
    for r in sample_rows:
        writer.writerow(r)
    return output.getvalue()

def parse_and_validate_csv(file_storage):
    """
    Reads uploaded CSV, normalizes headers, validates every row,
    and returns a structured preview response.
    """
    if not file_storage or not file_storage.filename:
        return {'success': False, 'message': "No file provided."}

    content_bytes = file_storage.read()
    if not content_bytes:
        return {'success': False, 'message': "Uploaded CSV file is empty."}

    # Handle UTF-8 with BOM, Latin-1 fallback
    decoded = None
    for enc in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
        try:
            decoded = content_bytes.decode(enc)
            break
        except Exception:
            continue

    if decoded is None:
        return {'success': False, 'message': "Could not decode file. Please upload a standard UTF-8 CSV."}

    f = io.StringIO(decoded)
    reader = csv.reader(f)

    try:
        headers_raw = next(reader)
    except StopIteration:
        return {'success': False, 'message': "CSV file has no content."}

    # Normalize headers
    header_map = {}
    standard_keys = {
        'fullname': 'full_name', 'name': 'full_name', 'full_name': 'full_name',
        'email': 'email', 'email_address': 'email',
        'mobile': 'mobile', 'mobile_number': 'mobile', 'phone': 'mobile', 'phone_number': 'mobile',
        'password': 'password', 'temp_password': 'password', 'temporary_password': 'password',
        'role': 'role', 'user_role': 'role',
        'occupation': 'occupation',
        'college': 'college', 'college_name': 'college', 'institution': 'college',
        'department': 'department', 'dept': 'department', 'branch': 'department',
        'section': 'section', 'sec': 'section',
        'study_year': 'study_year', 'year': 'study_year', 'year_sem': 'study_year', 'semester': 'study_year',
        'roll_number': 'roll_number', 'roll_no': 'roll_number', 'registration_number': 'roll_number', 'reg_no': 'roll_number',
        'enrolled_session': 'enrolled_session', 'session': 'enrolled_session', 'batch': 'enrolled_session'
    }

    for idx, h in enumerate(headers_raw):
        clean_h = re.sub(r'[^a-zA-Z0-9_]', '', h.strip().lower().replace(' ', '_'))
        if clean_h in standard_keys:
            header_map[idx] = standard_keys[clean_h]

    # Check required core headers
    mapped_fields = set(header_map.values())
    if 'full_name' not in mapped_fields or 'email' not in mapped_fields:
        return {
            'success': False,
            'message': f"CSV is missing mandatory headers: 'full_name' and/or 'email'. Found headers: {', '.join(headers_raw)}"
        }

    conn = get_db_connection()
    if not conn:
        return {'success': False, 'message': "Database connection failed."}

    seen_emails_in_csv = set()
    seen_rolls_in_csv = set()
    preview_rows = []
    valid_count = 0
    invalid_count = 0
    duplicate_count = 0

    try:
        with conn.cursor() as cursor:
            for row_idx, row in enumerate(reader):
                if not row or all(not str(c).strip() for c in row):
                    continue  # Skip blank rows

                row_num = row_idx + 2  # 1-based, accounts for header

                # Build record dict
                raw_record = {}
                for col_idx, val in enumerate(row):
                    if col_idx in header_map:
                        raw_record[header_map[col_idx]] = val.strip()

                email = raw_record.get('email', '').strip().lower()
                roll = raw_record.get('roll_number', '').strip().lower()

                is_dup_in_csv = (email in seen_emails_in_csv) or (roll and roll in seen_rolls_in_csv)
                if is_dup_in_csv:
                    duplicate_count += 1

                is_valid, errors, cleaned = validate_user_fields(
                    raw_record,
                    existing_emails_set=seen_emails_in_csv,
                    existing_rolls_set=seen_rolls_in_csv,
                    db_cursor=cursor
                )

                if is_valid:
                    valid_count += 1
                    seen_emails_in_csv.add(cleaned['email'])
                    if cleaned.get('roll_number'):
                        seen_rolls_in_csv.add(cleaned['roll_number'].lower())
                    status = 'valid'
                    status_text = 'Ready to Import'
                else:
                    invalid_count += 1
                    status = 'invalid'
                    status_text = '; '.join(f"{k}: {v}" for k, v in errors.items())

                preview_rows.append({
                    'row_number': row_num,
                    'full_name': raw_record.get('full_name', ''),
                    'email': raw_record.get('email', ''),
                    'mobile': raw_record.get('mobile', ''),
                    'role': raw_record.get('role', 'Student') or 'Student',
                    'department': raw_record.get('department', ''),
                    'roll_number': raw_record.get('roll_number', ''),
                    'college': raw_record.get('college', ''),
                    'enrolled_session': raw_record.get('enrolled_session', ''),
                    'status': status,
                    'status_text': status_text,
                    'errors': errors,
                    'cleaned': cleaned if is_valid else None
                })

        return {
            'success': True,
            'total_rows': len(preview_rows),
            'valid_rows': valid_count,
            'invalid_rows': invalid_count,
            'duplicate_rows': duplicate_count,
            'rows_to_create': valid_count,
            'preview_data': preview_rows
        }
    finally:
        conn.close()

def execute_csv_import(preview_rows, admin_id=None, req=None):
    """
    Imports all valid records from preview into the database inside a transaction.
    Returns result metrics and generates error report if any.
    """
    if not preview_rows:
        return {'success': False, 'message': "No records to import."}

    conn = get_db_connection()
    if not conn:
        return {'success': False, 'message': "Database connection failed."}

    created = 0
    skipped = 0
    failed_rows = []

    try:
        with conn.cursor() as cursor:
            insert_sql = """
                INSERT INTO Users (
                    full_name, email, mobile, phone_number, password_hash, role,
                    enrolled_session, occupation, college, department, section,
                    study_year, roll_number, must_change_password,
                    temporary_password_created_at, created_by, is_blocked
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, 1,
                    NOW(), %s, 0
                )
            """

            for item in preview_rows:
                if item.get('status') != 'valid' or not item.get('cleaned'):
                    skipped += 1
                    failed_rows.append({
                        'row_number': item.get('row_number', ''),
                        'email': item.get('email', ''),
                        'roll_number': item.get('roll_number', ''),
                        'reason': item.get('status_text', 'Validation failed')
                    })
                    continue

                rec = item['cleaned']
                try:
                    pw_hash = hash_user_password(rec['password'])
                    cursor.execute(insert_sql, (
                        rec['full_name'], rec['email'], rec['mobile'], rec['mobile'],
                        pw_hash, rec['role'], rec['enrolled_session'], rec['occupation'],
                        rec['college'], rec['department'], rec['section'], rec['study_year'],
                        rec['roll_number'], admin_id
                    ))
                    created += 1
                except Exception as e:
                    skipped += 1
                    failed_rows.append({
                        'row_number': item.get('row_number', ''),
                        'email': rec.get('email', ''),
                        'roll_number': rec.get('roll_number', ''),
                        'reason': f"Database insert failed: {str(e)}"
                    })

        conn.commit()

        log_admin_action(
            admin_id,
            'USER_CSV_IMPORT',
            {'created': created, 'skipped': skipped, 'failed_count': len(failed_rows)},
            req
        )

        return {
            'success': True,
            'message': f"Import complete: {created} accounts created, {skipped} skipped.",
            'created_count': created,
            'skipped_count': skipped,
            'failed_count': len(failed_rows),
            'failed_rows': failed_rows
        }
    except Exception as e:
        conn.rollback()
        return {'success': False, 'message': f"Import transaction failed: {str(e)}"}
    finally:
        conn.close()

def generate_error_csv(failed_rows):
    """Generates downloadable error CSV with formula injection protection."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['row_number', 'email', 'roll_number', 'error_reason'])
    for r in failed_rows:
        writer.writerow([
            sanitize_csv_cell(r.get('row_number', '')),
            sanitize_csv_cell(r.get('email', '')),
            sanitize_csv_cell(r.get('roll_number', '')),
            sanitize_csv_cell(r.get('reason', ''))
        ])
    return output.getvalue()

def get_users_directory(search=None, role=None, department=None, session_name=None, status=None, must_change_pw=None, page=1, per_page=20):
    """
    Fetches paginated user list with multi-column search and filters.
    """
    conn = get_db_connection()
    if not conn:
        return {'users': [], 'total': 0, 'page': page, 'pages': 1}

    try:
        with conn.cursor() as cursor:
            where_clauses = ["1=1"]
            params = []

            if search:
                s = f"%{search.strip()}%"
                where_clauses.append("(u.full_name LIKE %s OR u.email LIKE %s OR u.roll_number LIKE %s OR u.college LIKE %s)")
                params.extend([s, s, s, s])

            if role:
                where_clauses.append("u.role = %s")
                params.append(role)

            if department:
                where_clauses.append("u.department = %s")
                params.append(department)

            if session_name:
                where_clauses.append("(u.enrolled_session = %s OR u.selected_session = %s)")
                params.extend([session_name, session_name])

            if status is not None and status != '':
                if status == 'active':
                    where_clauses.append("u.is_blocked = 0")
                elif status == 'blocked':
                    where_clauses.append("u.is_blocked = 1")

            if must_change_pw is not None and must_change_pw != '':
                val = 1 if str(must_change_pw) in ('1', 'true', 'yes') else 0
                where_clauses.append("u.must_change_password = %s")
                params.append(val)

            where_sql = " AND ".join(where_clauses)

            # Count total
            cursor.execute(f"SELECT COUNT(*) as total FROM Users u WHERE {where_sql}", tuple(params))
            total = cursor.fetchone()['total']

            # Pagination
            page = max(1, int(page))
            per_page = max(5, min(100, int(per_page)))
            offset = (page - 1) * per_page
            total_pages = max(1, (total + per_page - 1) // per_page)

            # Fetch rows
            query = f"""
                SELECT u.user_id, u.full_name, u.email, u.mobile, u.role,
                       u.college, u.department, u.section, u.study_year, u.roll_number,
                       u.enrolled_session, u.is_blocked, u.must_change_password,
                       u.temporary_password_created_at, u.password_changed_at,
                       u.created_at, u.created_by,
                       creator.full_name as creator_name
                FROM Users u
                LEFT JOIN Users creator ON u.created_by = creator.user_id
                WHERE {where_sql}
                ORDER BY u.user_id DESC
                LIMIT %s OFFSET %s
            """
            cursor.execute(query, tuple(params + [per_page, offset]))
            users = cursor.fetchall()

            for u in users:
                u['created_at_formatted'] = u['created_at'].strftime('%b %d, %Y') if isinstance(u.get('created_at'), datetime) else 'N/A'
                u['password_changed_at_formatted'] = u['password_changed_at'].strftime('%b %d, %Y') if isinstance(u.get('password_changed_at'), datetime) else 'Never'

            return {
                'users': users,
                'total': total,
                'page': page,
                'per_page': per_page,
                'pages': total_pages
            }
    finally:
        conn.close()

def reset_user_temp_password(user_id, admin_id=None, req=None):
    """
    Generates a new temporary password for a user and sets must_change_password=1.
    """
    conn = get_db_connection()
    if not conn:
        return {'success': False, 'message': "Database connection unavailable."}

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id, full_name, email FROM Users WHERE user_id=%s", (user_id,))
            user = cursor.fetchone()
            if not user:
                return {'success': False, 'message': "User not found."}

            new_temp_password = generate_temp_password()
            pw_hash = hash_user_password(new_temp_password)

            cursor.execute("""
                UPDATE Users
                SET password_hash=%s,
                    must_change_password=1,
                    temporary_password_created_at=NOW()
                WHERE user_id=%s
            """, (pw_hash, user_id))

        conn.commit()

        log_admin_action(
            admin_id,
            'USER_RESET_TEMP_PASSWORD',
            {'user_id': user_id, 'email': user['email']},
            req
        )

        return {
            'success': True,
            'message': f"Temporary password reset for {user['full_name']}.",
            'user_id': user_id,
            'email': user['email'],
            'temp_password': new_temp_password
        }
    except Exception as e:
        conn.rollback()
        return {'success': False, 'message': f"Failed to reset password: {str(e)}"}
    finally:
        conn.close()

def force_user_password_change(user_id, admin_id=None, req=None):
    """
    Flags an account to require a password change on next login without changing current password.
    """
    conn = get_db_connection()
    if not conn:
        return {'success': False, 'message': "Database connection unavailable."}

    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE Users SET must_change_password=1 WHERE user_id=%s", (user_id,))
        conn.commit()

        log_admin_action(admin_id, 'USER_FORCE_PASSWORD_CHANGE', {'user_id': user_id}, req)
        return {'success': True, 'message': "User will be forced to change password on next login."}
    except Exception as e:
        conn.rollback()
        return {'success': False, 'message': str(e)}
    finally:
        conn.close()
