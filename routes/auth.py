from flask import Blueprint, request, redirect, session, render_template, flash, jsonify, send_file
from utils import get_db_connection
import base64
import os
import time
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from session_manager import register_user_session, invalidate_user_session
from user_management_service import verify_user_password, hash_user_password
from official_assets_manager import log_admin_action, get_client_ip

# Rate limiting for password change attempts: { 'identifier': [timestamp, timestamp, ...] }
PASSWORD_CHANGE_ATTEMPTS = {}
MAX_PW_ATTEMPTS = 5
PW_WINDOW_SECONDS = 600  # 10 minutes

def is_pw_rate_limited(identifier):
    now = time.time()
    attempts = PASSWORD_CHANGE_ATTEMPTS.get(identifier, [])
    # Keep only attempts in window
    valid_attempts = [t for t in attempts if now - t < PW_WINDOW_SECONDS]
    PASSWORD_CHANGE_ATTEMPTS[identifier] = valid_attempts
    return len(valid_attempts) >= MAX_PW_ATTEMPTS

def record_pw_attempt(identifier):
    now = time.time()
    attempts = PASSWORD_CHANGE_ATTEMPTS.get(identifier, [])
    attempts.append(now)
    PASSWORD_CHANGE_ATTEMPTS[identifier] = attempts

auth_bp = Blueprint('auth', __name__, template_folder='../templates')

@auth_bp.route('/api/user/profile-image')
def get_profile_image():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT avatar FROM Users WHERE user_id=%s", (session['user_id'],))
            user = cursor.fetchone()
            if user and user.get('avatar'):
                return jsonify({'image': user['avatar']})
    finally:
        conn.close()
    
    return jsonify({'image': None})

@auth_bp.route('/api/user/update-profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401
    
    user_id = session['user_id']
    year_sem = request.form.get('year_sem')  # Format: "I/I sem", "II/II sem", etc.
    profile_image = request.files.get('profile_image')
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Handle Year/Semester update
            if year_sem and year_sem.strip():
                # Parse the year_sem value (e.g., "I/I sem" -> year="I", semester="I")
                parts = year_sem.replace(' sem', '').split('/')
                year = parts[0].strip() if len(parts) > 0 else ''
                semester = parts[1].strip() if len(parts) > 1 else ''
                
                cursor.execute("SELECT study_year, last_year_update FROM Users WHERE user_id=%s", (user_id,))
                user = cursor.fetchone()
                
                # Check for 90-day cooldown
                if user and user.get('last_year_update'):
                    last_update = user['last_year_update']
                    if isinstance(last_update, str):
                        last_update = datetime.strptime(last_update, '%Y-%m-%d')
                    
                    days_since_update = (datetime.now() - last_update).days
                    if days_since_update < 90:
                        return jsonify({'success': False, 'message': f'Year/Semester can only be updated once every 90 days. {90 - days_since_update} days remaining.'})
                
                # Try to update both fields, fallback to just study_year if semester doesn't exist
                try:
                    cursor.execute("UPDATE Users SET study_year=%s, semester=%s, last_year_update=%s WHERE user_id=%s", 
                               (year, semester, datetime.now().strftime('%Y-%m-%d'), user_id))
                except:
                    # Fallback: just update study_year
                    cursor.execute("UPDATE Users SET study_year=%s, last_year_update=%s WHERE user_id=%s", 
                               (year, datetime.now().strftime('%Y-%m-%d'), user_id))
                
                session['study_year'] = year
                session['semester'] = semester
            
            # Handle Profile Image upload (simple base64, no PIL required)
            if profile_image and profile_image.filename:
                try:
                    from PIL import Image
                    import io
                    
                    # Read image and create a PIL Image
                    img_data = profile_image.read()
                    img = Image.open(io.BytesIO(img_data))
                    
                    # Convert to RGBA if needed
                    if img.mode != 'RGBA':
                        img = img.convert('RGBA')
                    
                    # Calculate crop box for center square (minimum dimension)
                    min_dim = min(img.size)
                    left = (img.width - min_dim) // 2
                    top = (img.height - min_dim) // 2
                    right = left + min_dim
                    bottom = top + min_dim
                    
                    # Crop to square center
                    img = img.crop((left, top, right, bottom))
                    
                    # Resize to standard avatar size (200x200 for good quality)
                    img = img.resize((200, 200), Image.Resampling.LANCZOS)
                    
                    # Convert back to RGB and save as PNG for best quality
                    if img.mode == 'RGBA':
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        background.paste(img, mask=img.split()[3])
                        img = background
                    
                    # Save to bytes
                    output = io.BytesIO()
                    img.save(output, format='PNG', quality=90)
                    image_data = base64.b64encode(output.getvalue()).decode('utf-8')
                    image_data = f"data:image/png;base64,{image_data}"
                except Exception as e:
                    # Fallback: just save raw base64 without processing
                    image_data = base64.b64encode(profile_image.read()).decode('utf-8')
                    extension = profile_image.filename.rsplit('.', 1)[-1].lower() if '.' in profile_image.filename else 'png'
                    mime_types = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png', 'gif': 'gif'}
                    mime = mime_types.get(extension, 'png')
                    image_data = f"data:image/{mime};base64,{image_data}"
                
                cursor.execute("UPDATE Users SET avatar=%s WHERE user_id=%s", (image_data, user_id))
                
                return jsonify({'success': True, 'message': 'Profile updated successfully', 'image': image_data})
            
        conn.commit()
        return jsonify({'success': True, 'message': 'Profile updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()

@auth_bp.route('/change-password', methods=['GET', 'POST'])
def change_password_page():
    if 'user_id' not in session:
        return redirect('/login')

    if request.method == 'GET':
        return render_template('change_password.html')

    # Handle standard form POST submission
    current_pw = request.form.get('current_password', '').strip()
    new_pw = request.form.get('new_password', '').strip()
    confirm_pw = request.form.get('confirm_password', '').strip()

    user_id = session['user_id']
    ip = get_client_ip(request)
    rate_key = f"{user_id}_{ip}"

    if is_pw_rate_limited(rate_key):
        flash('Too many failed attempts. Please try again after 10 minutes.', 'danger')
        return render_template('change_password.html')

    if not current_pw or not new_pw or not confirm_pw:
        flash('All password fields are required.', 'danger')
        return render_template('change_password.html')

    if len(new_pw) < 6:
        flash('New password must be at least 6 characters.', 'danger')
        return render_template('change_password.html')

    if new_pw != confirm_pw:
        flash('New password and confirmation do not match.', 'danger')
        return render_template('change_password.html')

    if new_pw == current_pw:
        flash('New password cannot be the same as your current password.', 'danger')
        return render_template('change_password.html')

    conn = get_db_connection()
    if not conn:
        flash('Database connection failed. Please try again.', 'danger')
        return render_template('change_password.html')

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT password_hash FROM Users WHERE user_id=%s", (user_id,))
            user = cursor.fetchone()
            if not user or not verify_user_password(user['password_hash'], current_pw):
                record_pw_attempt(rate_key)
                flash('Current password is incorrect.', 'danger')
                return render_template('change_password.html')

            new_hash = hash_user_password(new_pw)
            cursor.execute("""
                UPDATE Users
                SET password_hash=%s,
                    must_change_password=0,
                    password_changed_at=NOW()
                WHERE user_id=%s
            """, (new_hash, user_id))

        conn.commit()
        session['must_change_password'] = 0
        log_admin_action(user_id, 'PASSWORD_CHANGED', {'role': session.get('role')}, request)

        flash('Password updated successfully! Welcome to your dashboard.', 'success')
        role = session.get('role')
        if role == 'Admin': return redirect('/admin')
        elif role == 'Coordinator': return redirect('/coordinator')
        else: return redirect('/student')
    except Exception as e:
        conn.rollback()
        flash(f'An error occurred: {str(e)}', 'danger')
        return render_template('change_password.html')
    finally:
        conn.close()

@auth_bp.route('/api/auth/change-password', methods=['POST'])
@auth_bp.route('/api/user/change-password', methods=['POST'])
def api_change_password():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    user_id = session['user_id']
    ip = get_client_ip(request)
    rate_key = f"{user_id}_{ip}"

    if is_pw_rate_limited(rate_key):
        return jsonify({
            'success': False,
            'message': 'Too many failed attempts. Please try again after 10 minutes.'
        }), 429

    data = request.get_json() or request.form
    current_password = data.get('current_password', '').strip()
    new_password = data.get('new_password', '').strip()
    confirm_password = data.get('confirm_password', '').strip()

    if not current_password or not new_password:
        return jsonify({'success': False, 'message': 'Current and new password are required.'}), 400

    if len(new_password) < 6:
        return jsonify({'success': False, 'message': 'Password must be at least 6 characters.'}), 400

    if confirm_password and new_password != confirm_password:
        return jsonify({'success': False, 'message': 'New password and confirmation do not match.'}), 400

    if new_password == current_password:
        return jsonify({'success': False, 'message': 'New password cannot be identical to current password.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection unavailable.'}), 500

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT password_hash FROM Users WHERE user_id=%s", (user_id,))
            user = cursor.fetchone()
            if not user or not verify_user_password(user['password_hash'], current_password):
                record_pw_attempt(rate_key)
                return jsonify({'success': False, 'message': 'Current password is incorrect.'}), 400

            new_hash = hash_user_password(new_password)
            cursor.execute("""
                UPDATE Users
                SET password_hash=%s,
                    must_change_password=0,
                    password_changed_at=NOW()
                WHERE user_id=%s
            """, (new_hash, user_id))

        conn.commit()
        session['must_change_password'] = 0
        log_admin_action(user_id, 'PASSWORD_CHANGED', {'role': session.get('role')}, request)

        role = session.get('role')
        target_redirect = '/admin' if role == 'Admin' else ('/coordinator' if role == 'Coordinator' else '/student')

        return jsonify({
            'success': True,
            'message': 'Password changed successfully.',
            'redirect': target_redirect
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()

@auth_bp.route('/api/auth/password-change-required')
def api_password_change_required():
    if 'user_id' not in session:
        return jsonify({'logged_in': False, 'required': False})
    return jsonify({
        'logged_in': True,
        'required': session.get('must_change_password') == 1,
        'user_id': session.get('user_id'),
        'role': session.get('role')
    })

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_id = request.form.get('login_id', '').strip()
        password = request.form.get('password', '').strip()
        remember = request.form.get('remember')
        conn = get_db_connection()
        user = None
        if conn:
            with conn.cursor() as cursor:
                # Query user by email or roll_number (case-insensitive where applicable)
                cursor.execute("SELECT * FROM Users WHERE email=%s OR roll_number=%s", (login_id, login_id))
                user = cursor.fetchone()
            conn.close()

        if user and verify_user_password(user['password_hash'], password):
            # SECURITY CHECK: IS USER BLOCKED?
            if user.get('is_blocked', 0) == 1:
                return render_template('login.html',
                                       error="ACCOUNT LOCKED",
                                       details="Your account was locked due to exam security violations. Please contact your Coordinator or Admin to unlock.")

            session.permanent = True if remember else False
            session['user_id'] = user['user_id']
            session['role'] = user['role']
            session['name'] = user['full_name']
            session['department'] = user.get('department', '')
            session['study_year'] = user.get('study_year', '')
            session['section'] = user.get('section', '')
            
            enrolled_session = user.get('enrolled_session', '')
            if not enrolled_session and user.get('role') == 'Student':
                enrolled_session = user.get('batch', '')
            session['enrolled_session'] = enrolled_session

            must_change_pw = int(user.get('must_change_password') or 0)
            session['must_change_password'] = must_change_pw

            # Single-Device & 25-minute Inactivity Tracking for Student and Coordinator
            if user['role'] in ['Student', 'Coordinator']:
                token = register_user_session(user['user_id'], user['role'])
                session['session_token'] = token
                session['last_activity'] = time.time()

            # Forced first-login password change redirect
            if must_change_pw == 1:
                return redirect('/change-password')

            if user['role'] == 'Admin': return redirect('/admin')
            elif user['role'] == 'Coordinator': return redirect('/coordinator')
            else: return redirect('/student')

        return render_template('login.html', error="Invalid Credentials")
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    conn = get_db_connection()

    # --- POST: HANDLE REGISTRATION FORM ---
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        mobile = request.form.get('mobile')
        password = request.form.get('password')
        selected_session = request.form.get('session_select')  # Gets the Title

        # Details
        occupation = request.form.get('occupation')
        college = request.form.get('college') if occupation == 'Student' else None
        dept = request.form.get('department') if occupation == 'Student' else None
        section = request.form.get('section') if occupation == 'Student' else None
        year = request.form.get('year') if occupation == 'Student' else None
        roll_no = request.form.get('roll_number') if occupation == 'Student' else None
        designation = request.form.get('designation') if occupation == 'Employee' else None

        # Team Logic
        goal_type = request.form.get('goal_type')
        team_name = request.form.get('team_name') if goal_type == 'Team' else None

        # Capture Team Member IDs (New Requirement)
        members = []
        ids = []
        if goal_type == 'Team':
            for i in range(1, 5):
                m_name = request.form.get(f'member_{i}')
                m_id = request.form.get(f'id_{i}')
                if m_name:
                    members.append(m_name)
                if m_id:
                    ids.append(m_id)

        team_members_str = ", ".join(members) if members else None

        try:
            with conn.cursor() as cursor:
                # Check for existing email
                cursor.execute("SELECT * FROM Users WHERE email=%s", (email,))
                if cursor.fetchone():
                    # Re-fetch sessions to show error properly
                    cursor.execute("SELECT DISTINCT batch FROM Quizzes WHERE batch IS NOT NULL AND batch != '' AND reg_status = 1 ORDER BY batch DESC")
                    sessions = cursor.fetchall()
                    return render_template('register.html', error="Email already registered!", sessions=sessions)

                # Insert
                sql = """
                    INSERT INTO Users (
                        full_name, email, mobile, password_hash, role,
                        enrolled_session, occupation, college, department, section,
                        study_year, roll_number, designation, goal_type,
                        team_name, team_members
                    )
                    VALUES (%s, %s, %s, %s, 'Student', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(sql, (
                    full_name, email, mobile, password, selected_session,
                    occupation, college, dept, section, year, roll_no, designation,
                    goal_type, team_name, team_members_str
                ))
            conn.commit()
            return redirect('/login')
        except Exception as e:
            return f"Registration Error: {e}"
        finally:
            conn.close()

    # --- GET: LOAD REGISTRATION PAGE ---
    sessions = []
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT DISTINCT batch FROM Quizzes WHERE batch IS NOT NULL AND batch != '' AND reg_status = 1 ORDER BY batch DESC")
                sessions = cursor.fetchall()
        finally:
            conn.close()

    return render_template('register.html', sessions=sessions)

@auth_bp.route('/logout')
def logout():
    user_id = session.get('user_id')
    if user_id:
        invalidate_user_session(user_id)
    session.clear()
    reason = request.args.get('reason')
    if reason:
        return redirect(f'/login?reason={reason}')
    return redirect('/')


@auth_bp.route('/api/user/migrate-db')
def migrate_user_db():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401
    
    conn = get_db_connection()
    log = []
    try:
        with conn.cursor() as cursor:
            try:
                cursor.execute("ALTER TABLE Users ADD COLUMN avatar TEXT")
                log.append("avatar column added")
            except:
                pass
            try:
                cursor.execute("ALTER TABLE Users ADD COLUMN last_year_update DATE")
                log.append("last_year_update column added")
            except:
                pass
        conn.commit()
        return jsonify({'success': True, 'log': log})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()

