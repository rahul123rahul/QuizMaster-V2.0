from flask import Blueprint, request, redirect, render_template, flash, session
import base64
from utils import get_db_connection

home_bp = Blueprint('home', __name__, template_folder='../templates')

@home_bp.route('/')
def home():
    conn = get_db_connection()
    stats = {'students': 0, 'exams': 0, 'quizzes': 0}
    events = []
    latest_banner = None
    all_banners = []

    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT COUNT(*) as c FROM Users WHERE role=%s', ('Student',))
                stats['students'] = cursor.fetchone()['c']
                cursor.execute('SELECT COUNT(*) as c FROM Quiz_Attempts')
                stats['exams'] = cursor.fetchone()['c']
                cursor.execute('SELECT COUNT(*) as c FROM Quizzes')
                stats['quizzes'] = cursor.fetchone()['c']

                cursor.execute('SELECT title, category, duration_minutes FROM Quizzes ORDER BY quiz_id DESC LIMIT 3')
                events = cursor.fetchall()

                cursor.execute('SELECT * FROM Banners ORDER BY id DESC LIMIT 1')
                latest_banner = cursor.fetchone()

                if session.get('role') == 'Admin':
                    cursor.execute('SELECT * FROM Banners ORDER BY id DESC')
                    all_banners = cursor.fetchall()
        finally:
            conn.close()

    return render_template('home.html', stats=stats, events=events, banner=latest_banner, all_banners=all_banners)

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
                cursor.execute('ALTER TABLE Quizzes ADD COLUMN year VARCHAR(20)')
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