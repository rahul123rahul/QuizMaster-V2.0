from flask import Blueprint, request, redirect, session, render_template, flash, jsonify, send_file
from utils import get_db_connection
import base64
import os
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename

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

@auth_bp.route('/api/user/change-password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401
    
    data = request.get_json()
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')
    
    if not current_password or not new_password:
        return jsonify({'success': False, 'message': 'All fields are required'})
    
    if len(new_password) < 6:
        return jsonify({'success': False, 'message': 'Password must be at least 6 characters'})
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT password_hash FROM Users WHERE user_id=%s", (session['user_id'],))
            user = cursor.fetchone()
            
            if user['password_hash'] != current_password:
                return jsonify({'success': False, 'message': 'Current password is incorrect'})
            
            cursor.execute("UPDATE Users SET password_hash=%s WHERE user_id=%s", (new_password, session['user_id']))
        conn.commit()
        return jsonify({'success': True, 'message': 'Password changed successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_id = request.form.get('login_id')
        password = request.form.get('password')
        remember = request.form.get('remember')
        conn = get_db_connection()
        user = None
        if conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM Users WHERE (email=%s OR roll_number=%s) AND password_hash=%s", (login_id, login_id, password))
                user = cursor.fetchone()
            conn.close()

        if user:
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
    session.clear()
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

