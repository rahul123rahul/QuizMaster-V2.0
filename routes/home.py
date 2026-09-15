from flask import Blueprint, request, redirect, render_template, flash, session, jsonify
import base64
import os
import json
from utils import get_db_connection

home_bp = Blueprint('home', __name__, template_folder='../templates')

METRICS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'platform_metrics.json')

def get_monotonic_stats(current_stats):
    """
    Ensures platform stats (active learners, exams completed, live challenges)
    never decrease once increased (monotonic non-dropping guarantee).
    """
    os.makedirs(os.path.dirname(METRICS_FILE), exist_ok=True)
    saved = {'students': 0, 'exams': 0, 'quizzes': 0}
    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
        except Exception:
            saved = {'students': 0, 'exams': 0, 'quizzes': 0}

    cur_students = int(current_stats.get('students', 0) or 0)
    cur_exams = int(current_stats.get('exams', 0) or 0)
    cur_quizzes = int(current_stats.get('quizzes', 0) or 0)

    monotonic = {
        'students': max(cur_students, int(saved.get('students', 0) or 0)),
        'exams': max(cur_exams, int(saved.get('exams', 0) or 0)),
        'quizzes': max(cur_quizzes, int(saved.get('quizzes', 0) or 0))
    }

    if monotonic != saved:
        try:
            with open(METRICS_FILE, 'w', encoding='utf-8') as f:
                json.dump(monotonic, f, indent=2)
        except Exception as e:
            print(f"Notice: Could not persist metrics file: {e}")

    return monotonic

@home_bp.route('/')
def home():
    conn = get_db_connection()
    raw_stats = {'students': 0, 'exams': 0, 'quizzes': 0}
    events = []
    latest_banner = None
    all_banners = []

    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT COUNT(*) as c FROM Users WHERE role=%s', ('Student',))
                raw_stats['students'] = cursor.fetchone()['c']
                cursor.execute('SELECT COUNT(*) as c FROM Quiz_Attempts')
                raw_stats['exams'] = cursor.fetchone()['c']
                cursor.execute('SELECT COUNT(*) as c FROM Quizzes')
                raw_stats['quizzes'] = cursor.fetchone()['c']

                cursor.execute('SELECT title, category, duration_minutes FROM Quizzes ORDER BY quiz_id DESC LIMIT 3')
                events = cursor.fetchall()

                cursor.execute('SELECT * FROM Banners ORDER BY id DESC LIMIT 1')
                latest_banner = cursor.fetchone()

                if session.get('role') == 'Admin':
                    cursor.execute('SELECT * FROM Banners ORDER BY id DESC')
                    all_banners = cursor.fetchall()
        except Exception as e:
            print(f"Error querying home page stats: {e}")
        finally:
            conn.close()

    stats = get_monotonic_stats(raw_stats)
    return render_template('home.html', stats=stats, events=events, banner=latest_banner, all_banners=all_banners)

@home_bp.route('/api/platform_stats')
def api_platform_stats():
    conn = get_db_connection()
    raw_stats = {'students': 0, 'exams': 0, 'quizzes': 0}
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT COUNT(*) as c FROM Users WHERE role=%s', ('Student',))
                raw_stats['students'] = cursor.fetchone()['c']
                cursor.execute('SELECT COUNT(*) as c FROM Quiz_Attempts')
                raw_stats['exams'] = cursor.fetchone()['c']
                cursor.execute('SELECT COUNT(*) as c FROM Quizzes')
                raw_stats['quizzes'] = cursor.fetchone()['c']
        except Exception:
            pass
        finally:
            conn.close()
    stats = get_monotonic_stats(raw_stats)
    return jsonify({
        'status': 'success',
        'stats': stats,
        'display': {
            'students': f"{stats['students']}+",
            'exams': f"{stats['exams']}+",
            'quizzes': f"{stats['quizzes']}"
        }
    })


@home_bp.route('/admin/upload_banner', methods=['POST'])
def upload_banner():
    if session.get('role') != 'Admin':
        return redirect('/')
    file = request.files.get('banner_image')
    caption = request.form.get('caption')

    if file:
        image_data = 'data:image/png;base64,' + base64.b64encode(file.read()).decode('utf-8')
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('INSERT INTO Banners (image_data, caption) VALUES (%s, %s)', (image_data, caption))
        conn.commit()
        conn.close()
        flash('Banner uploaded successfully!', 'success')
    return redirect('/admin#banners')

@home_bp.route('/admin/delete_banner', methods=['POST'])
def delete_banner():
    if session.get('role') != 'Admin':
        return redirect('/')
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('DELETE FROM Banners ORDER BY id DESC LIMIT 1')
    conn.commit()
    conn.close()
    flash('Latest banner deleted.', 'info')
    return redirect('/admin#banners')

@home_bp.route('/admin/fix_db')
def fix_db_schema():
    if session.get('role') != 'Admin':
        return 'Denied. Login as Admin first.'
    conn = get_db_connection()
    log = []
    try:
        with conn.cursor() as cursor:
            try:
                cursor.execute('ALTER TABLE Users ADD COLUMN section VARCHAR(20)')
            except Exception as e:
                log.append(f'Users Table (section): {e}')

            try:
                cursor.execute('ALTER TABLE Users ADD COLUMN study_year VARCHAR(20)')
            except Exception as e:
                log.append(f'Users Table (study_year): {e}')

            try:
                cursor.execute('ALTER TABLE Quizzes ADD COLUMN section VARCHAR(50)')
            except Exception as e:
                log.append(f'Quizzes Table (section): {e}')

            try:
                cursor.execute('ALTER TABLE Quizzes ADD COLUMN year VARCHAR(255)')
            except Exception as e:
                log.append(f'Quizzes Table (year): {e}')

            try:
                cursor.execute('ALTER TABLE Questions ADD COLUMN module VARCHAR(100) DEFAULT %s', ('General',))
            except Exception as e:
                log.append(f'Questions Table: {e}')

            try:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS Batches (
                        batch_id INT AUTO_INCREMENT PRIMARY KEY,
                        batch_name VARCHAR(100) NOT NULL UNIQUE
                    )''')
                log.append('Batches Table: Checked/Created successfully.')
            except Exception as e:
                log.append(f'Batches Table Creation: {e}')
        conn.commit()
        log_str = '<br>'.join(log) if log else 'Columns added successfully!'
        return f'<h3>Database Update Log:</h3><pre>{log_str}</pre><br><a href=\"/admin\">Back to Admin</a>'
    finally:
        conn.close()