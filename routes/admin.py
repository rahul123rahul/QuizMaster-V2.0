from flask import Blueprint, request, redirect, render_template, jsonify, flash, session, Response, current_app, send_file
from utils import get_db_connection
from datetime import datetime
import csv
import io
import json
import os
import docx
from werkzeug.utils import secure_filename

admin_bp = Blueprint('admin', __name__, template_folder='../templates', url_prefix='/admin')

def require_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'Admin':
            from flask import request
            if request.content_type and 'application/json' in request.content_type:
                return jsonify({'error': 'Admin access required', 'success': False}), 401
            return redirect('/')
        return f(*args, **kwargs)
    return decorated

def require_admin_or_coordinator(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') not in ['Admin', 'Coordinator']:
            from flask import request
            if request.content_type and 'application/json' in request.content_type:
                return jsonify({'error': 'Admin or Coordinator access required', 'success': False}), 401
            return redirect('/')
        return f(*args, **kwargs)
    return decorated

@admin_bp.route('/')
@require_admin
def dashboard():
    quizzes, questions, attempts, coordinators, all_students, winners, all_banners, batches = [], [], [], [], [], [], [], []
    total_students, total_exams, avg_score = 0, 0, 0
    filter_quiz_id = request.args.get('filter_quiz_id')

    conn = get_db_connection()
    if not conn:
        return render_template('error.html', error_title='Database Error', error_message='Cannot connect to MySQL database. Please ensure MySQL server is running.'), 500

    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM Quizzes')
            quizzes = cursor.fetchall()

            try:
                cursor.execute('SELECT batch_name as batch FROM Batches ORDER BY batch_name DESC')
                batches = cursor.fetchall()
            except Exception:
                batches = []

            q_query = 'SELECT q.*, COALESCE(z.title, %s) as session_name FROM Questions q LEFT JOIN Quizzes z ON q.quiz_id = z.quiz_id'
            q_params = ['General']
            if filter_quiz_id and filter_quiz_id != 'all':
                q_query += ' WHERE q.quiz_id = %s'
                q_params.append(filter_quiz_id)
            q_query += ' ORDER BY q.question_id DESC'
            cursor.execute(q_query, tuple(q_params))
            questions = cursor.fetchall()

            cursor.execute('''
                SELECT a.*, u.full_name, u.department, u.study_year, u.team_name, u.goal_type,
                       COALESCE(q.title, a.quiz_title, 'Assessment') AS title, a.certificate_approved
                FROM Quiz_Attempts a
                JOIN Users u ON a.user_id=u.user_id
                LEFT JOIN Quizzes q ON a.quiz_id=q.quiz_id
                ORDER BY a.total_score DESC
            ''')
            attempts = cursor.fetchall()

            cursor.execute('SELECT * FROM Users WHERE role=%s', ('Coordinator',))
            coordinators = cursor.fetchall()

            cursor.execute('SELECT * FROM Users WHERE role=%s', ('Student',))
            all_students = cursor.fetchall()

            cursor.execute('SELECT * FROM Banners ORDER BY id DESC')
            all_banners = cursor.fetchall()

            if attempts:
                total_students = len(set(a['user_id'] for a in attempts))
                total_exams = len(attempts)
                avg_score = round(sum(a['total_score'] for a in attempts) / total_exams, 1)
                high_score = max(a['total_score'] for a in attempts)
                winners = [a for a in attempts if a['total_score'] == high_score]
    finally:
        conn.close()

    return render_template('admin_dashboard.html',
        stats={'students': total_students, 'exams': total_exams, 'avg': avg_score},
        attempts=attempts, all_students=all_students, coordinators=coordinators,
        quizzes=quizzes, questions=questions, winners=winners,
        all_banners=all_banners, current_filter=filter_quiz_id, batches=batches)

@admin_bp.route('/manage_centers')
@require_admin_or_coordinator
def manage_centers():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('''
            SELECT c.*,
            (SELECT COUNT(*) FROM Users u WHERE u.center_id = c.center_id) as allocated_count
            FROM Exam_Centers c
        ''')
        centers = cursor.fetchall()
    conn.close()
    return render_template('manage_centers.html', centers=centers)

@admin_bp.route('/add_center', methods=['POST'])
@require_admin
def add_center():
    rows = int(request.form['rows'])
    cols = int(request.form['cols'])
    capacity = rows * cols

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('''
            INSERT INTO Exam_Centers (center_name, city, address, total_rows, total_cols, capacity)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (request.form['name'], request.form['city'], request.form['address'], rows, cols, capacity))
    conn.commit()
    conn.close()
    return redirect('/admin/manage_centers')

@admin_bp.route('/auto_allocate', methods=['POST'])
@require_admin
def auto_allocate():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('SELECT * FROM Exam_Centers')
        centers = cursor.fetchall()

        cursor.execute('SELECT user_id FROM Users WHERE center_id IS NULL AND role=%s', ('Student',))
        students = cursor.fetchall()

        student_idx = 0
        total_students = len(students)

        for center in centers:
            if student_idx >= total_students:
                break

            for r in range(1, center['total_rows'] + 1):
                for c in range(1, center['total_cols'] + 1):
                    if student_idx >= total_students:
                        break

                    cursor.execute('SELECT 1 FROM Users WHERE center_id=%s AND seat_row=%s AND seat_col=%s',
                                  (center['center_id'], r, c))
                    if cursor.fetchone():
                        continue

                    uid = students[student_idx]['user_id']
                    cursor.execute('UPDATE Users SET center_id=%s, seat_row=%s, seat_col=%s WHERE user_id=%s',
                                  (center['center_id'], r, c, uid))
                    student_idx += 1

    conn.commit()
    conn.close()
    return redirect('/admin/manage_centers')

@admin_bp.route('/sessions')
@admin_bp.route('/manage_sessions')
@require_admin_or_coordinator
def manage_sessions():
    conn = get_db_connection()
    quizzes = []
    batches = []
    all_system_batches = []
    if conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM Quizzes ORDER BY start_time DESC')
            quizzes = cursor.fetchall()
            cursor.execute('SELECT batch_name as batch FROM Batches ORDER BY batch_name DESC')
            batches = cursor.fetchall()
            cursor.execute('SELECT * FROM Batches ORDER BY batch_name DESC')
            all_system_batches = cursor.fetchall()
        conn.close()
    return render_template('manage_sessions.html', quizzes=quizzes, batches=batches, all_system_batches=all_system_batches)

@admin_bp.route('/create_session')
@require_admin_or_coordinator
def create_session_page():
    conn = get_db_connection()
    batches = []
    if conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT batch_name as batch FROM Batches ORDER BY batch_name DESC')
            batches = cursor.fetchall()
        conn.close()
    return render_template('create_session.html', batches=batches)

@admin_bp.route('/create_quiz_session', methods=['POST'])
@require_admin_or_coordinator
def create_quiz_session():
    title = request.form.get('title')
    batch = request.form.get('batch')
    year = request.form.get('year')
    duration = request.form.get('duration')
    start_time = request.form.get('start_time')
    cert_status = request.form.get('cert_status', '0')
    description = request.form.get('description')
    category = request.form.get('category') or 'Exam'
    department = request.form.get('department')
    section = request.form.get('section')
    
    conn = get_db_connection()
    if conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'INSERT INTO Quizzes (title, batch, year, duration_minutes, total_marks, start_time, instructions, category, department, section) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
                (title, batch, year, duration, cert_status, start_time, description, category, department, section)
            )
        conn.commit()
        conn.close()
    
    flash('Session created successfully!', 'success')
    return redirect('/admin/sessions')

@admin_bp.route('/edit_session/<int:quiz_id>', methods=['GET', 'POST'])
@require_admin_or_coordinator
def edit_session_page(quiz_id):
    conn = get_db_connection()

    if request.method == 'POST':
        title = request.form.get('title')
        batch = request.form.get('batch')
        year = request.form.get('year')
        duration = request.form.get('duration')
        start_time = request.form.get('start_time')
        cert_status = request.form.get('cert_status', '0')
        description = request.form.get('description')
        category = request.form.get('category') or 'Exam'
        department = request.form.get('department')
        section = request.form.get('section')
        
        if conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    'UPDATE Quizzes SET title=%s, batch=%s, year=%s, duration_minutes=%s, total_marks=%s, start_time=%s, instructions=%s, category=%s, department=%s, section=%s WHERE quiz_id=%s',
                    (title, batch, year, duration, cert_status, start_time, description, category, department, section, quiz_id)
                )
            conn.commit()
            conn.close()
        flash('Session updated successfully!', 'success')
        return redirect('/admin/sessions')

    quiz = None
    batches = []
    if conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM Quizzes WHERE quiz_id=%s', (quiz_id,))
            quiz = cursor.fetchone()
            cursor.execute('SELECT batch_name as batch FROM Batches ORDER BY batch_name DESC')
            batches = cursor.fetchall()
        conn.close()
    return render_template('edit_session.html', quiz=quiz, batches=batches)

@admin_bp.route('/add_batch', methods=['POST'])
@require_admin
def add_batch():
    batch_name = request.form.get('batch_name')
    if batch_name:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('INSERT INTO Batches (batch_name) VALUES (%s) ON DUPLICATE KEY UPDATE batch_name=%s', (batch_name, batch_name))
        conn.commit()
        conn.close()
        flash('Batch added successfully!', 'success')
    return redirect('/admin/sessions')

@admin_bp.route('/delete_batch/<int:batch_id>')
@require_admin
def delete_batch(batch_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('DELETE FROM Batches WHERE batch_id=%s', (batch_id,))
    conn.commit()
    conn.close()
    return redirect('/admin/sessions')

@admin_bp.route('/delete_session/<int:quiz_id>')
@require_admin
def delete_session(quiz_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Cache quiz metadata on all attempts before deleting so student past results are preserved forever
        cursor.execute('''
            UPDATE Quiz_Attempts a
            JOIN Quizzes q ON a.quiz_id = q.quiz_id
            SET a.quiz_title = COALESCE(a.quiz_title, q.title),
                a.total_marks = COALESCE(a.total_marks, q.total_marks, (SELECT COALESCE(SUM(marks), 100) FROM Questions WHERE quiz_id = q.quiz_id)),
                a.batch = COALESCE(a.batch, q.batch),
                a.total_questions = COALESCE(a.total_questions, (SELECT COUNT(*) FROM Questions WHERE quiz_id = q.quiz_id))
            WHERE a.quiz_id = %s
        ''', (quiz_id,))
        # Disassociate attempt from quiz so cascade doesn't affect it
        cursor.execute('UPDATE Quiz_Attempts SET quiz_id = NULL WHERE quiz_id = %s', (quiz_id,))
        cursor.execute('DELETE FROM Quizzes WHERE quiz_id=%s', (quiz_id,))
    conn.commit()
    conn.close()
    flash('Session deleted successfully! Student past results have been archived and preserved.', 'success')
    return redirect('/admin/sessions')

@admin_bp.route('/toggle_reg/<int:quiz_id>/<int:status>')
@require_admin
def toggle_registration(quiz_id, status):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('UPDATE Quizzes SET reg_status=%s WHERE quiz_id=%s', (status, quiz_id))
    conn.commit()
    conn.close()
    return redirect('/admin/sessions')

def get_filtered_quiz_results(args):
    conn = get_db_connection()
    results = []
    batches = []
    departments = []
    sessions = []

    current_batch = args.get('batch', '').strip()
    current_quiz_id = args.get('quiz_id', '').strip()
    current_dept = args.get('department', '').strip()
    current_sec = args.get('section', '').strip()
    current_year = args.get('year', '').strip()

    if conn:
        with conn.cursor() as cursor:
            # Fetch distinct batches for dropdown
            try:
                cursor.execute('''
                    SELECT DISTINCT batch FROM (
                        SELECT enrolled_session as batch FROM Users WHERE role='Student' AND enrolled_session IS NOT NULL AND enrolled_session != ''
                        UNION
                        SELECT batch FROM Quizzes WHERE batch IS NOT NULL AND batch != ''
                    ) b_all ORDER BY batch ASC
                ''')
                batches = cursor.fetchall()
            except Exception:
                batches = []

            # Fetch distinct assessment sessions for dropdown
            try:
                cursor.execute('SELECT quiz_id, title FROM Quizzes ORDER BY title ASC')
                sessions = cursor.fetchall()
            except Exception:
                sessions = []

            # Fetch distinct departments for dropdown
            try:
                cursor.execute('''
                    SELECT DISTINCT department FROM Users 
                    WHERE role='Student' AND department IS NOT NULL AND department != '' 
                    ORDER BY department ASC
                ''')
                departments = cursor.fetchall()
            except Exception:
                departments = []

            query = '''
                SELECT a.*, 
                       u.full_name, u.email, u.roll_number, u.department, u.section, u.study_year, u.enrolled_session,
                       COALESCE(q.title, a.quiz_title, 'Archived Assessment') AS quiz_title,
                       COALESCE(q.title, a.quiz_title, 'Archived Assessment') AS title,
                       COALESCE(q.batch, a.batch, '') AS batch,
                       COALESCE(q.duration_minutes, 0) AS duration_minutes,
                       COALESCE(
                           (SELECT SUM(marks) FROM Questions WHERE quiz_id = a.quiz_id),
                           q.total_marks,
                           a.total_marks,
                           0
                       ) AS total_marks,
                       COALESCE(
                           (SELECT COUNT(*) FROM Questions WHERE quiz_id = a.quiz_id),
                           a.total_questions,
                           0
                       ) AS total_questions,
                       COALESCE(
                           (SELECT COUNT(*) FROM Quiz_Responses WHERE attempt_id = a.attempt_id AND (is_attempted = 1 OR (selected_option IS NOT NULL AND selected_option != ''))),
                           0
                       ) AS attempted_count
                FROM Quiz_Attempts a
                JOIN Users u ON a.user_id = u.user_id
                LEFT JOIN Quizzes q ON a.quiz_id = q.quiz_id
                WHERE 1=1
            '''
            params = []

            if current_batch:
                query += ' AND (q.batch = %s OR a.batch = %s OR u.enrolled_session = %s)'
                params.extend([current_batch, current_batch, current_batch])
            if current_quiz_id and current_quiz_id != 'all':
                query += ' AND a.quiz_id = %s'
                params.append(current_quiz_id)
            if current_dept:
                query += ' AND u.department = %s'
                params.append(current_dept)
            if current_sec:
                query += ' AND u.section = %s'
                params.append(current_sec)
            if current_year:
                query += ' AND (u.study_year = %s OR q.year = %s)'
                params.extend([current_year, current_year])

            query += ' ORDER BY a.attempt_id DESC'
            cursor.execute(query, tuple(params))
            raw_results = cursor.fetchall()
        conn.close()

        for r in raw_results:
            start = r.get('start_time')
            end = r.get('end_time') or r.get('submitted_at')

            duration_seconds = 0
            if start and end:
                try:
                    delta = (end - start).total_seconds()
                    duration_seconds = max(0, int(delta))
                except Exception:
                    duration_seconds = 0
            elif start and r.get('status') == 'In-Progress':
                try:
                    delta = (datetime.now() - start).total_seconds()
                    duration_seconds = max(0, int(delta))
                except Exception:
                    duration_seconds = 0

            minutes = duration_seconds // 60
            seconds = duration_seconds % 60

            if duration_seconds > 0:
                if minutes >= 60:
                    hours = minutes // 60
                    rem_m = minutes % 60
                    short_timing = f"{hours}h {rem_m:02d}m {seconds:02d}s"
                else:
                    short_timing = f"{minutes:02d}m {seconds:02d}s"
            elif r.get('status') == 'In-Progress':
                short_timing = "Ongoing"
            else:
                short_timing = "--"

            attempted_count = int(r.get('attempted_count') or 0)
            total_questions = int(r.get('total_questions') or 0)

            # Answers attempted per minute
            if duration_seconds > 0 and attempted_count > 0:
                mins_float = duration_seconds / 60.0
                per_minute_attempted = round(attempted_count / mins_float, 2)
            else:
                per_minute_attempted = 0.0

            r['duration_seconds'] = duration_seconds
            r['short_timing'] = short_timing
            r['attempted_count'] = attempted_count
            r['total_questions'] = total_questions
            r['per_minute_attempted'] = per_minute_attempted
            results.append(r)

    total_candidates = len(results)
    if total_candidates > 0:
        avg_score = round(sum(float(r.get('total_score') or 0) for r in results) / total_candidates, 1)
        avg_attempted = round(sum(r.get('attempted_count', 0) for r in results) / total_candidates, 1)
        avg_total_qs = round(sum(r.get('total_questions', 0) for r in results) / total_candidates, 1)

        timed_results = [r for r in results if r.get('duration_seconds', 0) > 0]
        if timed_results:
            avg_dur_sec = int(sum(r['duration_seconds'] for r in timed_results) / len(timed_results))
            avg_m = avg_dur_sec // 60
            avg_s = avg_dur_sec % 60
            avg_short_timing = f"{avg_m:02d}m {avg_s:02d}s"
            avg_rate = round(sum(r['per_minute_attempted'] for r in timed_results) / len(timed_results), 2)
        else:
            avg_short_timing = "--"
            avg_rate = 0.0
    else:
        avg_score = 0
        avg_attempted = 0
        avg_total_qs = 0
        avg_short_timing = "--"
        avg_rate = 0.0

    summary = {
        'total_candidates': total_candidates,
        'avg_score': avg_score,
        'avg_attempted': avg_attempted,
        'avg_total_qs': avg_total_qs,
        'avg_short_timing': avg_short_timing,
        'avg_rate': avg_rate
    }

    return results, batches, departments, sessions, summary, {
        'current_batch': current_batch,
        'current_quiz_id': current_quiz_id,
        'current_dept': current_dept,
        'current_sec': current_sec,
        'current_year': current_year
    }

@admin_bp.route('/results')
@require_admin_or_coordinator
def manage_results():
    results, batches, departments, sessions, summary, current_filters = get_filtered_quiz_results(request.args)
    return render_template(
        'admin_results.html',
        results=results,
        attempts=results,
        batches=batches,
        departments=departments,
        sessions=sessions,
        summary=summary,
        **current_filters
    )

@admin_bp.route('/download_results_csv')
@admin_bp.route('/export_results')
@require_admin_or_coordinator
def download_results_csv():
    results, _, _, _, summary, _ = get_filtered_quiz_results(request.args)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'S.No', 'Roll No', 'Student Name', 'Email', 'Department', 'Section',
        'Year/Sem', 'Batch', 'Exam Title', 'Status', 'Score', 'Total Marks',
        'Total Questions', 'Answer Attempted', 'Time Taken (Short Timing)',
        'Answers Attempted Per Minute', 'Submitted At'
    ])

    for idx, r in enumerate(results, 1):
        writer.writerow([
            idx,
            r.get('roll_number') or '',
            r.get('full_name') or '',
            r.get('email') or '',
            r.get('department') or '',
            r.get('section') or '',
            r.get('study_year') or '',
            r.get('enrolled_session') or r.get('batch') or '',
            r.get('quiz_title') or r.get('title') or '',
            r.get('status') or '',
            r.get('total_score') if r.get('total_score') is not None else 0,
            r.get('total_marks') or 0,
            r.get('total_questions') or 0,
            r.get('attempted_count') or 0,
            r.get('short_timing') or '--',
            r.get('per_minute_attempted') or 0.0,
            r.get('submitted_at') or r.get('end_time') or ''
        ])

    # Summary Row at the bottom
    if results:
        writer.writerow([])
        writer.writerow([
            'SUMMARY / AVERAGE', '', '', '', '', '', '', '', '',
            f"Total: {summary['total_candidates']}",
            f"Avg Score: {summary['avg_score']}",
            '',
            f"Avg Qs: {summary['avg_total_qs']}",
            f"Avg Attempted: {summary['avg_attempted']}",
            f"Avg Time: {summary['avg_short_timing']}",
            f"Avg Rate: {summary['avg_rate']}/min",
            ''
        ])

    filename = f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )

@admin_bp.route('/approve_cert/<int:attempt_id>')
@require_admin
def approve_cert(attempt_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('UPDATE Quiz_Attempts SET certificate_approved=1 WHERE attempt_id=%s', (attempt_id,))
    conn.commit()
    conn.close()
    return redirect('/admin/results')

@admin_bp.route('/generate_manual_cert', methods=['POST'])
@require_admin
def generate_manual_cert():
    from certificate_generator import generate_certificate_pdf
    user_id = request.form.get('user_id')
    quiz_id = request.form.get('quiz_id')

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('''
            SELECT a.*, u.full_name, u.email, q.title
            FROM Quiz_Attempts a
            JOIN Users u ON a.user_id = u.user_id
            JOIN Quizzes q ON a.quiz_id = q.quiz_id
            WHERE a.user_id=%s AND a.quiz_id=%s
        ''', (user_id, quiz_id))
        attempt = cursor.fetchone()
    conn.close()

    if attempt:
        pdf_data = generate_certificate_pdf(attempt['full_name'], attempt['title'], attempt['total_score'])
        return pdf_data
    return 'Attempt not found', 404

@admin_bp.route('/announce_winner', methods=['POST'])
@require_admin
def announce_winner():
    winner_id = request.form.get('winner_id')
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('UPDATE Quiz_Attempts SET is_winner=1 WHERE attempt_id=%s', (winner_id,))
    conn.commit()
    conn.close()
    return redirect('/admin')

@admin_bp.route('/clear_announcement')
@require_admin
def clear_announcement():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('UPDATE Quiz_Attempts SET is_winner=0')
    conn.commit()
    conn.close()
    return redirect('/admin')

@admin_bp.route('/students')
@require_admin_or_coordinator
def manage_students_page():
    from utils import build_student_query
    query, params = build_student_query(request.args)
    conn = get_db_connection()
    students, batches, departments = [], [], []
    if conn:
        with conn.cursor() as cursor:
            cursor.execute(query, tuple(params))
            students = cursor.fetchall()
            cursor.execute('SELECT DISTINCT enrolled_session as batch FROM Users WHERE role=%s AND enrolled_session IS NOT NULL AND enrolled_session != %s ORDER BY enrolled_session DESC', ('Student', ''))
            batches = cursor.fetchall()
            cursor.execute('SELECT DISTINCT department FROM Users WHERE role=%s AND department IS NOT NULL AND department != %s', ('Student', ''))
            departments = cursor.fetchall()
        conn.close()
    return render_template('manage_students.html', students=students, batches=batches, departments=departments)

@admin_bp.route('/coordinators')
@require_admin
def manage_coordinators_page():
    conn = get_db_connection()
    coordinators = []
    if conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM Users WHERE role=%s', ('Coordinator',))
            coordinators = cursor.fetchall()
        conn.close()
    return render_template('manage_coordinators.html', coordinators=coordinators)

@admin_bp.route('/edit_student', defaults={'user_id': None})
@admin_bp.route('/edit_student/<int:user_id>')
@require_admin
def edit_student_page(user_id):
    if not user_id:
        user_id = request.args.get('user_id')

    if not user_id:
        flash('Please select a student from the list to edit.', 'warning')
        return redirect('/admin/students')

    conn = get_db_connection()
    user = None
    sessions = []
    centers = []

    # 1. Base registration form departments
    registration_depts = [
        'Civil',
        'Mechanical',
        'CSE',
        'CSE- Artificial Intelligence and Machine Learning',
        'CSE- Cyber Security',
        'CSE- Data Science',
        'AI&DS- Artificial Intelligence and Data Science',
        'ECE'
    ]
    dept_set = set(registration_depts)

    if conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM Users WHERE user_id=%s', (user_id,))
            user = cursor.fetchone()
            cursor.execute('SELECT batch_name as batch FROM Batches ORDER BY batch_name')
            sessions = cursor.fetchall()
            cursor.execute('SELECT center_id, center_name, capacity, allocated_count FROM Exam_Centers ORDER BY center_name')
            centers = cursor.fetchall()

            # 2. Departments from registered users
            try:
                cursor.execute("SELECT DISTINCT department FROM Users WHERE department IS NOT NULL AND department != ''")
                for d in cursor.fetchall():
                    val = d['department'].strip()
                    if val:
                        dept_set.add(val)
            except Exception:
                pass

            # 3. Departments added by Admin in Quizzes / Sessions
            try:
                cursor.execute("SELECT DISTINCT department FROM Quizzes WHERE department IS NOT NULL AND department != ''")
                for q in cursor.fetchall():
                    raw = q.get('department') or ''
                    for part in raw.split(','):
                        clean_part = part.strip()
                        if clean_part:
                            dept_set.add(clean_part)
            except Exception:
                pass
        conn.close()

    if not user:
        flash('Student record not found.', 'danger')
        return redirect('/admin/students')

    if user.get('department'):
        dept_set.add(user['department'].strip())

    additional_depts = sorted([d for d in dept_set if d not in registration_depts])
    all_depts = registration_depts + additional_depts

    return render_template('edit_student.html', user=user, sessions=sessions, centers=centers, departments=all_depts)

@admin_bp.route('/update_student', methods=['POST'])
@require_admin_or_coordinator
def update_student():
    user_id = request.form.get('user_id')
    if not user_id:
        flash('Invalid student ID.', 'danger')
        return redirect('/admin/students')

    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip()
    mobile = request.form.get('mobile', '').strip()
    roll_number = request.form.get('roll_number', '').strip()
    college = request.form.get('college', '').strip()
    department = request.form.get('department', '').strip()
    custom_department = request.form.get('custom_department', '').strip()
    if department == '__custom__' or not department:
        if custom_department:
            department = custom_department

    section = request.form.get('section', '').strip()
    study_year = request.form.get('study_year', '').strip()
    enrolled_session = request.form.get('enrolled_session', '').strip()

    new_center_id = request.form.get('allotted_center_id')
    try:
        new_center_id = int(new_center_id) if new_center_id else None
    except (ValueError, TypeError):
        new_center_id = None

    seat_row = request.form.get('seat_row', '').strip()
    seat_col = request.form.get('seat_col', '').strip()
    try:
        seat_row_val = int(seat_row) if seat_row else None
    except (ValueError, TypeError):
        seat_row_val = None

    try:
        seat_col_val = int(seat_col) if seat_col else None
    except (ValueError, TypeError):
        seat_col_val = None

    try:
        att_p = int(request.form.get('attendance_present', 0))
    except (ValueError, TypeError):
        att_p = 0

    try:
        att_t = int(request.form.get('attendance_total', 0))
    except (ValueError, TypeError):
        att_t = 0

    try:
        is_blocked = int(request.form.get('is_blocked', 0))
    except (ValueError, TypeError):
        is_blocked = 0

    new_password = request.form.get('password', '').strip()

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                query = '''
                    UPDATE Users
                    SET full_name=%s,
                        email=%s,
                        mobile=%s,
                        phone_number=%s,
                        roll_number=%s,
                        college=%s,
                        department=%s,
                        section=%s,
                        study_year=%s,
                        enrolled_session=%s,
                        allotted_center_id=%s,
                        center_id=%s,
                        seat_row=%s,
                        seat_col=%s,
                        attendance_present=%s,
                        attendance_total=%s,
                        is_blocked=%s
                '''
                params = [
                    full_name, email, mobile, mobile, roll_number, college,
                    department, section, study_year, enrolled_session,
                    new_center_id, new_center_id, seat_row_val, seat_col_val,
                    att_p, att_t, is_blocked
                ]

                if new_password:
                    query += ', password_hash=%s'
                    params.append(new_password)

                query += ' WHERE user_id=%s'
                params.append(user_id)

                cursor.execute(query, tuple(params))
            conn.commit()
            flash(f'Student "{full_name}" updated successfully!', 'success')
        except Exception as e:
            conn.rollback()
            print(f"Error updating student: {e}")
            flash(f'Failed to update student: {str(e)}', 'danger')
        finally:
            conn.close()

    return redirect('/admin/students')

@admin_bp.route('/delete_user/<int:user_id>')
@require_admin
def delete_user(user_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('DELETE FROM Users WHERE user_id=%s', (user_id,))
    conn.commit()
    conn.close()
    return redirect('/admin/students')

@admin_bp.route('/toggle_block/<int:user_id>/<int:status>')
@require_admin
def toggle_block(user_id, status):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('UPDATE Users SET is_blocked=%s WHERE user_id=%s', (status, user_id))
    conn.commit()
    conn.close()
    return redirect('/admin/students')

@admin_bp.route('/add_coordinator', methods=['POST'])
@require_admin
def add_coordinator():
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    password = request.form.get('password')
    conn = get_db_connection()
    if conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM Users WHERE email=%s', (email,))
            if cursor.fetchone():
                return 'Error: User already exists!'
            cursor.execute('INSERT INTO Users (full_name, email, password_hash, role) VALUES (%s, %s, %s, %s)', (full_name, email, password, 'Coordinator'))
        conn.commit()
        conn.close()
    return redirect('/admin/coordinators')

@admin_bp.route('/bulk_update_batch', methods=['POST'])
@require_admin
def bulk_update_batch():
    user_ids = request.form.getlist('user_ids')
    new_batch = request.form.get('new_batch')

    if user_ids and new_batch:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            placeholders = ','.join(['%s'] * len(user_ids))
            sql = f'UPDATE Users SET enrolled_session=%s WHERE user_id IN ({placeholders})'
            cursor.execute(sql, [new_batch] + user_ids)
        conn.commit()
        conn.close()
    return redirect('/admin/students')

@admin_bp.route('/mark_attendance', methods=['POST'])
@require_admin_or_coordinator
def mark_attendance():
    all_ids = request.form.getlist('all_user_ids')
    present_ids = request.form.getlist('user_ids')

    if not all_ids:
        return redirect('/admin/students')

    all_set = set(all_ids)
    present_set = set(present_ids)
    absent_set = all_set - present_set

    conn = get_db_connection()
    with conn.cursor() as cursor:
        for uid in present_set:
            cursor.execute('UPDATE Users SET attendance_present = attendance_present + 1, attendance_total = attendance_total + 1 WHERE user_id=%s', (uid,))
        for uid in absent_set:
            cursor.execute('UPDATE Users SET attendance_total = attendance_total + 1 WHERE user_id=%s', (uid,))
    conn.commit()
    conn.close()
    return redirect('/admin/students')

@admin_bp.route('/ai_generate')
@require_admin
def ai_generate_page():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('SELECT quiz_id, title, batch, year as study_year FROM Quizzes ORDER BY quiz_id DESC')
        quizzes = cursor.fetchall()
    conn.close()
    return render_template('ai_generate.html', quizzes=quizzes)

@admin_bp.route('/ai_preview', methods=['GET', 'POST'])
@require_admin
def ai_preview_admin_page():
    from utils import generate_ai_questions, cache_ai_preview_state, render_ai_preview_page
    
    if request.method == 'GET':
        preview_token = request.args.get('preview_token')
        if not preview_token:
            flash('Missing preview token', 'error')
            return redirect('/admin/ai_generate')
        
        from utils import get_cached_ai_preview_state
        preview_state, token = get_cached_ai_preview_state(preview_token)
        
        if not preview_state:
            flash('Preview session expired or invalid', 'error')
            return redirect('/admin/ai_generate')
        
        return render_ai_preview_page(preview_state, token)
    
    # POST handler for generating questions
    
    content_type = request.content_type or ''
    if 'application/json' in content_type:
        data = request.get_json(silent=True) or {}
        topic = data.get('topic', '')
        difficulty = data.get('difficulty', 'Medium')
        count = int(data.get('count', 10))
        quiz_id = data.get('quiz_id')
        selected_batch = data.get('batch', '')
        selected_session = data.get('session', '')
        selected_branch = data.get('branch', '')
        selected_timing = data.get('timing', '')
    else:
        topic = request.form.get('topic', '')
        difficulty = request.form.get('difficulty', 'Medium')
        count = int(request.form.get('count', 10))
        quiz_id = request.form.get('quiz_id')
        selected_batch = request.form.get('batch', '')
        selected_session = request.form.get('session', '')
        selected_branch = request.form.get('branch', '')
        selected_timing = request.form.get('timing', '')
    
    is_json_request = 'application/json' in (request.content_type or '')
    
    preview_state = {
        'questions': [],
        'quiz_id': quiz_id,
        'generation_context': {},
        'generation_prompt': topic,
        'selected_batch': selected_batch,
        'selected_session': selected_session,
        'selected_branch': selected_branch,
        'selected_timing': selected_timing,
    }
    
    try:
        questions = generate_ai_questions(
            topic=topic,
            difficulty=difficulty,
            count=count,
            quiz_details={'quiz_id': quiz_id} if quiz_id else None
        )
        if not questions:
            raise ValueError("No questions were generated. Please check your API key and try again.")
        
        preview_state['questions'] = questions
        
    except Exception as e:
        error_msg = str(e)
        if is_json_request:
            return jsonify({'error': error_msg, 'success': False}), 500
        flash(f"Error generating questions: {error_msg}", "error")
        return redirect('/admin/ai_generate')
    
    if not questions or not isinstance(questions, list):
        if is_json_request:
            return jsonify({'error': 'Failed to generate valid questions', 'success': False}), 500
        flash("Failed to generate valid questions. Please try a different topic.", "error")
        return redirect('/admin/ai_generate')
    
    try:
        preview_token = cache_ai_preview_state(preview_state)
        
        if is_json_request:
            return jsonify({
                'success': True,
                'questions': questions,
                'preview_token': preview_token,
                'redirect_url': '/admin/ai_preview?preview_token=' + preview_token
            })
        
        return render_ai_preview_page(preview_state, preview_token)
    except Exception as e:
        if is_json_request:
            return jsonify({'error': str(e), 'success': False}), 500
        flash(f"Error rendering preview: {str(e)}", "error")
        return redirect('/admin/ai_generate')

@admin_bp.route('/delete_bulk_questions', methods=['POST'])
@require_admin_or_coordinator
def delete_bulk_questions():
    ids = request.form.getlist('q_ids')
    if ids:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            fmt = ','.join(['%s'] * len(ids))
            cursor.execute(f'DELETE FROM Questions WHERE question_id IN ({fmt})', tuple(ids))
        conn.commit()
        conn.close()
    if session.get('role') == 'Coordinator':
        return redirect('/coordinator#questions')
    return redirect('/admin#questions')

@admin_bp.route('/add_manual_question', methods=['POST'])
@require_admin_or_coordinator
def add_manual_question():
    quiz_id = request.form.get('quiz_id')
    q_type = (request.form.get('q_type') or request.form.get('real-q-type') or '').strip().upper()

    if not quiz_id:
        flash('Quiz/session is required.', 'error')
        return redirect('/admin')

    # Template posts: q_text, marks, module_name, opt_a/b/c/d, correct_opt, test_input/test_output
    module_name = request.form.get('module_name', 'General')
    marks = request.form.get('marks', 1)
    try:
        marks = int(marks)
    except Exception:
        marks = 1

    quiz_type = (request.form.get('q_type') or q_type or 'MCQ').strip().upper()
    if quiz_type not in {'MCQ', 'CODE'}:
        quiz_type = 'MCQ'

    question_text = (request.form.get('q_text') or '').strip()
    if not question_text:
        flash('Question text is required.', 'error')
        return redirect('/admin')

    opt_a = request.form.get('opt_a', '').strip()
    opt_b = request.form.get('opt_b', '').strip()
    opt_c = request.form.get('opt_c', '').strip()
    opt_d = request.form.get('opt_d', '').strip()
    correct_opt = (request.form.get('correct_opt') or '').strip().upper() or 'A'
    if correct_opt not in {'A', 'B', 'C', 'D'}:
        correct_opt = 'A'

    test_input = (request.form.get('test_input') or '').strip()
    test_output = (request.form.get('test_output') or '').strip()

    conn = get_db_connection()
    if not conn:
        flash('Database connection error.', 'error')
        return redirect('/admin')

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                '''
                INSERT INTO Questions
                    (quiz_id, question_type, question_text,
                     option_a, option_b, option_c, option_d, correct_option,
                     test_input, test_output,
                     marks, module)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ''',
                (
                    quiz_id,
                    quiz_type,
                    question_text,
                    opt_a,
                    opt_b,
                    opt_c,
                    opt_d,
                    correct_opt,
                    test_input,
                    test_output,
                    marks,
                    module_name,
                )
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f'Error adding question: {str(e)}', 'error')
    finally:
        conn.close()

    return redirect(f'/admin#question-bank')

@admin_bp.route('/export_students')
@require_admin_or_coordinator
def export_students():
    from utils import build_student_query
    query, params = build_student_query(request.args)
    conn = get_db_connection()
    users = []
    if conn:
        with conn.cursor() as cursor:
            cursor.execute(query, tuple(params))
            users = cursor.fetchall()
        conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Name', 'Email', 'Mobile', 'Role', 'Goal', 'Team', 'CenterID', 'Seat'])
    for u in users:
        seat_row = u.get('seat_row') or ''
        seat_col = u.get('seat_col') or ''
        seat_info = f'R{seat_row}-C{seat_col}'
        writer.writerow([
            u.get('user_id'), u.get('full_name'), u.get('email'), u.get('mobile'),
            u.get('occupation'), u.get('goal_type'), u.get('team_name'),
            u.get('allotted_center_id'), seat_info
        ])
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-disposition': 'attachment; filename=student_list.csv'})
 
@admin_bp.route('/content')
@admin_bp.route('/question_builder')
@admin_bp.route('/question_bank')
@require_admin_or_coordinator
def question_bank():
    category_filter = request.args.get('category', '').strip()
    quiz_id_filter = request.args.get('quiz_id', '').strip()
    module_filter = request.args.get('module', '').strip()
    subject_filter = request.args.get('subject', '').strip()
    difficulty_filter = request.args.get('difficulty', '').strip()
    status_filter = request.args.get('status', '').strip()
    sort_filter = request.args.get('sort', 'newest').strip()
    search_query = request.args.get('q', '').strip()

    conn = get_db_connection()
    if not conn:
        flash('Database connection error.', 'error')
        return redirect('/admin')

    questions = []
    quizzes = []
    batches = []
    unique_modules = []
    unique_subjects = []

    category_counts = {
        'all': 0,
        'mscq_single': 0,
        'mscq_multiple': 0,
        'mscq_select': 0,
        'fill_blank': 0,
        'true_false': 0,
        'image_mcq': 0
    }
    total_marks = 0
    published_count = 0
    draft_count = 0
    adv_settings = DEFAULT_ADVANCE_SETTINGS.copy()

    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT quiz_id, title FROM Quizzes ORDER BY title ASC')
            quizzes = cursor.fetchall()

            try:
                cursor.execute('SELECT batch_name as batch FROM Batches ORDER BY batch_name DESC')
                batches = cursor.fetchall()
            except Exception:
                batches = []

            cursor.execute("SELECT DISTINCT module FROM Questions WHERE module IS NOT NULL AND module != ''")
            m_rows = cursor.fetchall()
            unique_modules = [m['module'] for m in m_rows if m.get('module')]

            cursor.execute("SELECT DISTINCT subject FROM Questions WHERE subject IS NOT NULL AND subject != ''")
            s_rows = cursor.fetchall()
            unique_subjects = [s['subject'] for s in s_rows if s.get('subject')]

            base_query = '''
                SELECT q.*, COALESCE(z.title, 'General') as session_name 
                FROM Questions q 
                LEFT JOIN Quizzes z ON q.quiz_id = z.quiz_id
                WHERE 1=1
            '''
            params = []

            if quiz_id_filter and quiz_id_filter != 'all':
                base_query += ' AND q.quiz_id = %s'
                params.append(quiz_id_filter)

            if module_filter and module_filter != 'all':
                base_query += ' AND (q.module = %s OR q.subject = %s)'
                params.append(module_filter)
                params.append(module_filter)

            if subject_filter and subject_filter != 'all':
                base_query += ' AND q.subject = %s'
                params.append(subject_filter)

            if difficulty_filter and difficulty_filter != 'all':
                base_query += ' AND q.difficulty = %s'
                params.append(difficulty_filter)

            if status_filter and status_filter != 'all':
                base_query += " AND (q.status = %s OR (%s='Published' AND (q.status IS NULL OR q.status='')))"
                params.append(status_filter)
                params.append(status_filter)

            if category_filter and category_filter != 'all':
                if category_filter in ['mscq_single', 'single_choice']:
                    base_query += " AND (q.question_type = 'mscq_single' OR q.question_type = 'single_choice' OR q.question_type = 'mcq_single' OR q.question_type = 'MCQ' OR q.question_type = 'mcq')"
                elif category_filter in ['mscq_multiple', 'multiple_select']:
                    base_query += " AND (q.question_type = 'mscq_multiple' OR q.question_type = 'multiple_select' OR q.question_type = 'mcq_multiple')"
                elif category_filter in ['mscq_select', 'dropdown']:
                    base_query += " AND (q.question_type = 'mscq_select' OR q.question_type = 'dropdown')"
                elif category_filter in ['fill_blank', 'fillInTheBlanks']:
                    base_query += " AND (q.question_type = 'fill_blank' OR q.question_type = 'fillInTheBlanks')"
                elif category_filter in ['true_false', 'trueFalse']:
                    base_query += " AND (q.question_type = 'true_false' OR q.question_type = 'trueFalse')"
                elif category_filter in ['image_mcq', 'image', 'image_based', 'diagram']:
                    base_query += " AND (q.question_type = 'image_mcq' OR q.metadata_json LIKE '%image_url%' OR q.metadata_json LIKE '%image_mcq%')"
                elif category_filter in ['coding', 'code']:
                    base_query += " AND (q.question_type = 'coding' OR q.module = 'Coding')"
                else:
                    base_query += ' AND q.question_type = %s'
                    params.append(category_filter)

            if search_query:
                base_query += ''' AND (
                    q.question_text LIKE %s OR 
                    q.module LIKE %s OR 
                    q.subject LIKE %s OR 
                    q.topic LIKE %s OR 
                    q.tags LIKE %s
                )'''
                like_term = f'%{search_query}%'
                params.extend([like_term]*5)

            if sort_filter == 'oldest':
                base_query += ' ORDER BY q.question_id ASC'
            elif sort_filter == 'marks_high':
                base_query += ' ORDER BY q.marks DESC, q.question_id DESC'
            elif sort_filter == 'marks_low':
                base_query += ' ORDER BY q.marks ASC, q.question_id DESC'
            else:
                base_query += ' ORDER BY q.question_id DESC'

            cursor.execute(base_query, tuple(params))
            raw_questions = cursor.fetchall()

            # Global counts per 5 types
            count_query = 'SELECT question_type, COUNT(*) as c FROM Questions GROUP BY question_type'
            cursor.execute(count_query)
            count_rows = cursor.fetchall()
            total_all = 0
            for row in count_rows:
                qtype = row['question_type']
                c = row['c']
                total_all += c
                if qtype in ['mscq_single', 'single_choice', 'mcq_single', 'MCQ', 'mcq']:
                    category_counts['mscq_single'] += c
                elif qtype in ['mscq_multiple', 'multiple_select', 'mcq_multiple']:
                    category_counts['mscq_multiple'] += c
                elif qtype in ['mscq_select', 'dropdown']:
                    category_counts['mscq_select'] += c
                elif qtype in ['fill_blank', 'fillInTheBlanks']:
                    category_counts['fill_blank'] += c
                elif qtype in ['true_false', 'trueFalse']:
                    category_counts['true_false'] += c
                elif qtype in ['image_mcq', 'image', 'image_based', 'diagram']:
                    category_counts['image_mcq'] += c
            category_counts['all'] = total_all

            # Status counts
            try:
                cursor.execute('SELECT status, COUNT(*) as c FROM Questions GROUP BY status')
                st_rows = cursor.fetchall()
                for st in st_rows:
                    if st.get('status') == 'Draft':
                        draft_count += st['c']
                    else:
                        published_count += st['c']
            except Exception:
                published_count = total_all
                draft_count = 0

            adv_settings = DEFAULT_ADVANCE_SETTINGS.copy()
            try:
                cursor.execute('SELECT setting_value FROM System_Settings WHERE setting_key=%s', ('advance_question_settings',))
                s_row = cursor.fetchone()
                if s_row and s_row.get('setting_value'):
                    adv_settings.update(json.loads(s_row['setting_value']))
            except Exception:
                pass

            for q in raw_questions:
                total_marks += (q.get('marks') or 0)
                meta = {}
                if q.get('metadata_json'):
                    try:
                        meta = json.loads(q['metadata_json'])
                    except Exception:
                        meta = {}
                q['meta'] = meta
                if not q.get('status'):
                    q['status'] = 'Published'
                questions.append(q)

    except Exception as e:
        flash(f'Error fetching Question Bank: {str(e)}', 'error')
    finally:
        conn.close()

    return render_template(
        'question_bank.html',
        questions=questions,
        quizzes=quizzes,
        batches=batches,
        modules=unique_modules,
        subjects=unique_subjects,
        category_counts=category_counts,
        total_questions=len(questions),
        total_all_questions=category_counts['all'],
        published_count=published_count,
        draft_count=draft_count,
        total_marks=total_marks,
        current_category=category_filter or 'all',
        current_quiz_id=quiz_id_filter or 'all',
        current_module=module_filter or 'all',
        current_subject=subject_filter or 'all',
        current_difficulty=difficulty_filter or 'all',
        current_status=status_filter or 'all',
        current_sort=sort_filter or 'newest',
        current_q=search_query,
        advance_settings=adv_settings
    )

# --- DEDICATED QUESTION REPOSITORY ROUTE ---
@admin_bp.route('/repository')
@admin_bp.route('/question_repository')
@require_admin_or_coordinator
def question_repository():
    category_filter = request.args.get('category', '').strip()
    quiz_id_filter = request.args.get('quiz_id', '').strip()
    difficulty_filter = request.args.get('difficulty', '').strip()
    status_filter = request.args.get('status', '').strip()
    sort_filter = request.args.get('sort', 'newest').strip()
    search_query = request.args.get('q', '').strip()

    conn = get_db_connection()
    if not conn:
        flash('Database connection error.', 'error')
        return redirect('/admin')

    questions = []
    quizzes = []
    batches = []
    category_counts = {
        'all': 0,
        'mscq_single': 0,
        'mscq_multiple': 0,
        'mscq_select': 0,
        'fill_blank': 0,
        'true_false': 0,
        'image_mcq': 0
    }
    total_marks = 0
    published_count = 0
    draft_count = 0

    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT quiz_id, title FROM Quizzes ORDER BY title ASC')
            quizzes = cursor.fetchall()

            try:
                cursor.execute('SELECT batch_name as batch FROM Batches ORDER BY batch_name DESC')
                batches = cursor.fetchall()
            except Exception:
                batches = []

            base_query = '''
                SELECT q.*, COALESCE(z.title, 'General') as session_name 
                FROM Questions q 
                LEFT JOIN Quizzes z ON q.quiz_id = z.quiz_id
                WHERE 1=1
            '''
            params = []

            if quiz_id_filter and quiz_id_filter != 'all':
                base_query += ' AND q.quiz_id = %s'
                params.append(quiz_id_filter)

            if difficulty_filter and difficulty_filter != 'all':
                base_query += ' AND q.difficulty = %s'
                params.append(difficulty_filter)

            if status_filter and status_filter != 'all':
                base_query += ' AND q.status = %s'
                params.append(status_filter)

            if category_filter and category_filter != 'all':
                if category_filter == 'mscq_single':
                    base_query += " AND (q.question_type = 'mscq_single' OR q.question_type = 'single_choice' OR q.question_type = 'MCQ')"
                elif category_filter == 'mscq_multiple':
                    base_query += " AND (q.question_type = 'mscq_multiple' OR q.question_type = 'multiple_select')"
                elif category_filter == 'mscq_select':
                    base_query += " AND (q.question_type = 'mscq_select')"
                elif category_filter == 'fill_blank':
                    base_query += " AND (q.question_type = 'fill_blank' OR q.question_type = 'fillInTheBlanks')"
                elif category_filter == 'true_false':
                    base_query += " AND (q.question_type = 'true_false' OR q.question_type = 'trueFalse')"
                elif category_filter in ['image_mcq', 'image', 'image_based', 'diagram']:
                    base_query += " AND (q.question_type = 'image_mcq' OR q.metadata_json LIKE '%image_url%' OR q.metadata_json LIKE '%image_mcq%')"
                elif category_filter in ['coding', 'code']:
                    base_query += " AND (q.question_type = 'coding' OR q.module = 'Coding')"

            if search_query:
                base_query += ' AND (q.question_text LIKE %s OR q.question_id LIKE %s)'
                params.append(f'%{search_query}%')
                params.append(f'%{search_query}%')

            if sort_filter == 'oldest':
                base_query += ' ORDER BY q.question_id ASC'
            elif sort_filter == 'marks_high':
                base_query += ' ORDER BY q.marks DESC'
            else:
                base_query += ' ORDER BY q.question_id DESC'

            cursor.execute(base_query, tuple(params))
            raw_questions = cursor.fetchall()

            # Global category and status counts
            cursor.execute('''
                SELECT question_type, status, COUNT(*) as cnt, SUM(marks) as sm 
                FROM Questions 
                GROUP BY question_type, status
            ''')
            c_rows = cursor.fetchall()
            for r in c_rows:
                cnt = r['cnt']
                q_type = r['question_type']
                category_counts['all'] += cnt
                if q_type in ['mscq_single', 'single_choice', 'MCQ']:
                    category_counts['mscq_single'] += cnt
                elif q_type in ['mscq_multiple', 'multiple_select']:
                    category_counts['mscq_multiple'] += cnt
                elif q_type in ['mscq_select']:
                    category_counts['mscq_select'] += cnt
                elif q_type in ['fill_blank', 'fillInTheBlanks']:
                    category_counts['fill_blank'] += cnt
                elif q_type in ['true_false', 'trueFalse']:
                    category_counts['true_false'] += cnt
                elif q_type in ['image_mcq', 'image', 'image_based', 'diagram']:
                    category_counts['image_mcq'] += cnt

                if r.get('status') == 'Published':
                    published_count += cnt
                else:
                    draft_count += cnt

            for q in raw_questions:
                total_marks += (q.get('marks') or 0)
                meta = {}
                if q.get('metadata_json'):
                    try:
                        meta = json.loads(q['metadata_json'])
                    except Exception:
                        meta = {}
                q['meta'] = meta
                if not q.get('status'):
                    q['status'] = 'Published'
                questions.append(q)

    except Exception as e:
        flash(f'Error fetching Question Repository: {str(e)}', 'error')
    finally:
        conn.close()

    return render_template(
        'question_repository.html',
        questions=questions,
        quizzes=quizzes,
        batches=batches,
        category_counts=category_counts,
        total_questions=len(questions),
        total_all_questions=category_counts['all'],
        published_count=published_count,
        draft_count=draft_count,
        total_marks=total_marks,
        current_category=category_filter or 'all',
        current_quiz_id=quiz_id_filter or 'all',
        current_difficulty=difficulty_filter or 'all',
        current_status=status_filter or 'all',
        current_sort=sort_filter or 'newest',
        current_q=search_query
    )

@admin_bp.route('/question_bank/save', methods=['POST'])
@require_admin_or_coordinator
def save_question_bank():
    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form.to_dict()

    question_id = data.get('question_id')
    quiz_id = data.get('quiz_id')
    raw_type = (data.get('question_type') or 'mscq_single').strip()
    question_text = (data.get('question_text') or '').strip()

    try:
        marks = float(data.get('marks', 1) or 1)
        if marks < 0: marks = 1.0
    except (ValueError, TypeError):
        marks = 1.0

    try:
        negative_marks = float(data.get('negative_marks', 0.25) or 0.0)
        if negative_marks < 0: negative_marks = 0.0
    except (ValueError, TypeError):
        negative_marks = 0.0

    subject_name = (data.get('subject') or 'General').strip() or 'General'
    difficulty = (data.get('difficulty') or 'Medium').strip()
    status = (data.get('status') or 'Published').strip()
    explanation = (data.get('explanation') or '').strip()

    if not quiz_id or not question_text:
        if request.is_json:
            return jsonify({'success': False, 'error': 'Assessment Session and Question Statement are required.'}), 400
        flash('Assessment Session and Question Statement are required.', 'error')
        return redirect('/admin/content')

    # Normalize to 5 supported types
    question_type = 'mscq_single'
    if raw_type in ['mscq_single', 'single_choice', 'mcq_single', 'MCQ', 'single', 'mcq']:
        question_type = 'mscq_single'
    elif raw_type in ['mscq_multiple', 'multiple_select', 'mcq_multiple', 'multiple']:
        question_type = 'mscq_multiple'
    elif raw_type in ['mscq_select', 'dropdown', 'select']:
        question_type = 'mscq_select'
    elif raw_type in ['fill_blank', 'fillInTheBlanks']:
        question_type = 'fill_blank'
    elif raw_type in ['true_false', 'trueFalse']:
        question_type = 'true_false'
    elif raw_type in ['image_mcq', 'image', 'image_based', 'diagram']:
        question_type = 'image_mcq'

    meta = {}
    opt_a, opt_b, opt_c, opt_d, correct_opt = '', '', '', '', ''
    incoming_meta = data.get('meta') or {}
    if isinstance(data.get('metadata_json'), str) and data.get('metadata_json'):
        try:
            incoming_meta = json.loads(data['metadata_json'])
        except Exception:
            pass

    # 1. MSCQ Single Choice
    if question_type == 'mscq_single':
        options = incoming_meta.get('options') or data.get('options') or [
            {'id': 'A', 'text': data.get('opt_a', '')},
            {'id': 'B', 'text': data.get('opt_b', '')},
            {'id': 'C', 'text': data.get('opt_c', '')},
            {'id': 'D', 'text': data.get('opt_d', '')}
        ]
        correct_opt = incoming_meta.get('correct_id') or data.get('correctAnswer') or data.get('correct_opt', 'A')
        meta = {
            'options': options,
            'correctAnswer': correct_opt,
            'selectionType': 'single',
            'negativeMarks': negative_marks
        }
        if len(options) > 0: opt_a = options[0].get('text', '')
        if len(options) > 1: opt_b = options[1].get('text', '')
        if len(options) > 2: opt_c = options[2].get('text', '')
        if len(options) > 3: opt_d = options[3].get('text', '')

    # 2. MSCQ Multiple Choice
    elif question_type == 'mscq_multiple':
        options = incoming_meta.get('options') or data.get('options', [])
        correct_opt = incoming_meta.get('correctAnswer') or data.get('correctAnswer') or ''
        if not correct_opt and options:
            correct_opt = ', '.join([o.get('id', '') for o in options if o.get('is_correct')])
        meta = {
            'options': options,
            'correctAnswer': correct_opt,
            'selectionType': 'multiple',
            'negativeMarks': negative_marks
        }
        if len(options) > 0: opt_a = options[0].get('text', '')
        if len(options) > 1: opt_b = options[1].get('text', '')
        if len(options) > 2: opt_c = options[2].get('text', '')
        if len(options) > 3: opt_d = options[3].get('text', '')

    # 3. MSCQ Select Dropdown
    elif question_type == 'mscq_select':
        options = incoming_meta.get('options') or data.get('options', [])
        correct_opt = incoming_meta.get('correctAnswer') or data.get('correctAnswer', 'A')
        meta = {
            'options': options,
            'correctAnswer': correct_opt,
            'selectionType': 'select',
            'negativeMarks': negative_marks
        }
        if len(options) > 0: opt_a = options[0].get('text', '')
        if len(options) > 1: opt_b = options[1].get('text', '')
        if len(options) > 2: opt_c = options[2].get('text', '')
        if len(options) > 3: opt_d = options[3].get('text', '')

    # 4. Fill in the Blanks
    elif question_type == 'fill_blank':
        accepted = incoming_meta.get('acceptedAnswers') or data.get('acceptedAnswers') or []
        if not accepted and (data.get('correctAnswer') or incoming_meta.get('correctAnswer')):
            raw_ca = str(data.get('correctAnswer') or incoming_meta.get('correctAnswer', ''))
            accepted = [a.strip() for a in raw_ca.split('|') if a.strip()]
        cs = bool(incoming_meta.get('caseSensitive', False) if 'caseSensitive' in incoming_meta else data.get('caseSensitive', False))
        meta = {
            'acceptedAnswers': accepted,
            'correctAnswer': accepted[0] if accepted else '',
            'caseSensitive': cs,
            'negativeMarks': negative_marks
        }
        correct_opt = accepted[0] if accepted else ''

    # 5. True / False
    elif question_type == 'true_false':
        correct_val = incoming_meta.get('correctAnswer') or data.get('correctAnswer', 'B')
        if correct_val.upper() in ['TRUE', 'A']:
            correct_val = 'True'
        elif correct_val.upper() in ['FALSE', 'B']:
            correct_val = 'False'
        meta = {
            'correctAnswer': correct_val,
            'options': [{'id': 'A', 'text': 'True'}, {'id': 'B', 'text': 'False'}],
            'negativeMarks': negative_marks
        }
        correct_opt = correct_val
        opt_a = 'True'
        opt_b = 'False'

    # 6. Image MCQs (Diagram, Photograph, Chart, Map, Mathematical, Medical/Scientific)
    elif question_type == 'image_mcq':
        image_url = (incoming_meta.get('image_url') or data.get('image_url') or '').strip()
        image_position = (incoming_meta.get('image_position') or data.get('image_position') or 'above').strip().lower()
        if image_position not in ['above', 'below', 'beside']:
            image_position = 'above'
        image_category = (incoming_meta.get('image_category') or data.get('image_category') or 'Diagram').strip()
        selection_type = (incoming_meta.get('selectionType') or data.get('selectionType') or 'single').strip().lower()

        options = incoming_meta.get('options') or data.get('options') or [
            {'id': 'A', 'text': data.get('opt_a', '')},
            {'id': 'B', 'text': data.get('opt_b', '')},
            {'id': 'C', 'text': data.get('opt_c', '')},
            {'id': 'D', 'text': data.get('opt_d', '')}
        ]
        correct_opt = incoming_meta.get('correctAnswer') or incoming_meta.get('correct_id') or data.get('correctAnswer') or data.get('correct_opt', 'A')
        if selection_type == 'multiple' and not correct_opt and options:
            correct_opt = ', '.join([o.get('id', '') for o in options if o.get('is_correct')])

        meta = {
            'image_url': image_url,
            'image_position': image_position,
            'image_category': image_category,
            'selectionType': selection_type,
            'options': options,
            'correctAnswer': correct_opt,
            'negativeMarks': negative_marks
        }
        if len(options) > 0: opt_a = options[0].get('text', '')
        if len(options) > 1: opt_b = options[1].get('text', '')
        if len(options) > 2: opt_c = options[2].get('text', '')
        if len(options) > 3: opt_d = options[3].get('text', '')

    metadata_json_str = json.dumps(meta)

    conn = get_db_connection()
    if not conn:
        if request.is_json:
            return jsonify({'success': False, 'error': 'Database connection error'}), 500
        flash('Database connection error', 'error')
        return redirect('/admin/content')

    try:
        with conn.cursor() as cursor:
            if question_id:
                cursor.execute('''
                    UPDATE Questions SET
                        quiz_id=%s, question_type=%s, question_text=%s,
                        option_a=%s, option_b=%s, option_c=%s, option_d=%s,
                        correct_option=%s, marks=%s, module=%s, subject=%s,
                        difficulty=%s, status=%s, explanation=%s,
                        negative_marks=%s, metadata_json=%s
                    WHERE question_id=%s
                ''', (
                    quiz_id, question_type, question_text,
                    opt_a, opt_b, opt_c, opt_d,
                    correct_opt, marks, subject_name, subject_name,
                    difficulty, status, explanation,
                    negative_marks, metadata_json_str, question_id
                ))
            else:
                cursor.execute('''
                    INSERT INTO Questions
                        (quiz_id, question_type, question_text,
                         option_a, option_b, option_c, option_d,
                         correct_option, marks, module, subject,
                         difficulty, status, explanation,
                         negative_marks, metadata_json)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ''', (
                    quiz_id, question_type, question_text,
                    opt_a, opt_b, opt_c, opt_d,
                    correct_opt, marks, subject_name, subject_name,
                    difficulty, status, explanation,
                    negative_marks, metadata_json_str
                ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f'Error saving question: {str(e)}', 'error')
        return redirect('/admin/content')
    finally:
        conn.close()

    if request.is_json:
        return jsonify({'success': True, 'message': 'Question saved successfully!'})
    flash('Question saved successfully!', 'success')
    return redirect('/admin/content')

# --- BULK QUESTION AUTHORING CREATION API (+ Add Multiple Questions) ---
@admin_bp.route('/api/questions/bulk_create', methods=['POST'])
@require_admin_or_coordinator
def api_bulk_create_questions():
    data = request.get_json() or {}
    quiz_id = data.get('quiz_id')
    raw_questions = data.get('questions', [])

    if not quiz_id:
        return jsonify({'success': False, 'error': 'Assessment Session (quiz_id) is required.'}), 400
    if not raw_questions or not isinstance(raw_questions, list):
        return jsonify({'success': False, 'error': 'No questions list provided.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Database connection error.'}), 500

    saved_count = 0
    try:
        with conn.cursor() as cursor:
            for q in raw_questions:
                q_text = (q.get('question_text') or q.get('questionText') or '').strip()
                if not q_text: continue
                
                raw_type = q.get('question_type') or q.get('type') or 'mscq_single'
                if raw_type in ['mscq_single', 'single']: norm_type = 'mscq_single'
                elif raw_type in ['mscq_multiple', 'multiple']: norm_type = 'mscq_multiple'
                elif raw_type in ['mscq_select', 'select']: norm_type = 'mscq_select'
                elif raw_type in ['fill_blank', 'fillInTheBlanks']: norm_type = 'fill_blank'
                elif raw_type in ['true_false', 'trueFalse']: norm_type = 'true_false'
                else: norm_type = 'mscq_single'

                try:
                    marks = float(q.get('marks', 1))
                    if marks < 0: marks = 1.0
                except (ValueError, TypeError): marks = 1.0

                try:
                    neg = float(q.get('negative_marks') or q.get('negativeMarks') or 0.25)
                    if neg < 0: neg = 0.0
                except (ValueError, TypeError): neg = 0.0

                subject = q.get('subject') or 'General'
                difficulty = q.get('difficulty') or 'Medium'
                explanation = q.get('explanation') or ''
                status = q.get('status') or 'Published'

                options = q.get('options') or []
                correct_ans = str(q.get('correct_answer') or q.get('correctAnswer') or '').strip()

                meta = {
                    'options': options,
                    'correctAnswer': correct_ans,
                    'negativeMarks': neg,
                    'caseSensitive': bool(q.get('case_sensitive') or q.get('caseSensitive', False)),
                    'acceptedAnswers': [correct_ans] if correct_ans else []
                }

                opt_a = options[0].get('text', '') if len(options) > 0 else ''
                opt_b = options[1].get('text', '') if len(options) > 1 else ''
                opt_c = options[2].get('text', '') if len(options) > 2 else ''
                opt_d = options[3].get('text', '') if len(options) > 3 else ''

                cursor.execute('''
                    INSERT INTO Questions
                        (quiz_id, question_type, question_text,
                         option_a, option_b, option_c, option_d,
                         correct_option, marks, module, subject,
                         difficulty, status, explanation,
                         negative_marks, metadata_json)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ''', (
                    quiz_id, norm_type, q_text,
                    opt_a, opt_b, opt_c, opt_d,
                    correct_ans, marks, subject, subject,
                    difficulty, status, explanation,
                    neg, json.dumps(meta)
                ))
                saved_count += 1
            conn.commit()
            return jsonify({
                'success': True,
                'count': saved_count,
                'message': f"Successfully added {saved_count} questions."
            })
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

# --- FILE PARSER HELPER (JSON, CSV, DOCX) ---
def parse_questions_from_file(file_storage, filename):
    filename = filename.lower()
    raw_questions = []

    # 1. JSON FORMAT
    if filename.endswith('.json'):
        try:
            content = json.loads(file_storage.read().decode('utf-8'))
            items = content if isinstance(content, list) else content.get('questions', [])
            for idx, it in enumerate(items):
                raw_questions.append({
                    'id': it.get('id', idx + 1),
                    'type': it.get('type', 'mscq'),
                    'selectionType': it.get('selectionType', 'single'),
                    'questionText': it.get('questionText', ''),
                    'options': it.get('options', []),
                    'correctAnswer': str(it.get('correctAnswer', '')).strip(),
                    'marks': it.get('marks', 1),
                    'negativeMarks': it.get('negativeMarks', 0.25),
                    'explanation': it.get('explanation', ''),
                    'caseSensitive': bool(it.get('caseSensitive', False)),
                    'acceptedAnswers': it.get('acceptedAnswers', [])
                })
        except Exception as e:
            return [], [{'id': 0, 'questionText': 'JSON Parse Error', 'errors': [f'Invalid JSON format: {str(e)}']}]

    # 2. CSV FORMAT
    elif filename.endswith('.csv'):
        try:
            stream = io.StringIO(file_storage.read().decode('utf-8'))
            reader = csv.DictReader(stream)
            for idx, row in enumerate(reader):
                raw_opts = row.get('options', '')
                options_list = []
                if raw_opts:
                    opt_parts = [p.strip() for p in raw_opts.replace('\n', '|').split('|') if p.strip()]
                    for part in opt_parts:
                        if '.' in part:
                            letter, text = part.split('.', 1)
                            options_list.append({'id': letter.strip().upper(), 'text': text.strip()})
                        else:
                            letter = chr(65 + len(options_list))
                            options_list.append({'id': letter, 'text': part.strip()})

                cs = row.get('caseSensitive', '').lower() in ['true', '1', 'yes']
                raw_questions.append({
                    'id': row.get('id') or (idx + 1),
                    'type': row.get('type', 'mscq'),
                    'selectionType': row.get('selectionType', 'single'),
                    'questionText': row.get('questionText', ''),
                    'options': options_list,
                    'correctAnswer': str(row.get('correctAnswer', '')).strip(),
                    'marks': row.get('marks', 1),
                    'negativeMarks': row.get('negativeMarks', 0.25),
                    'explanation': row.get('explanation', ''),
                    'caseSensitive': cs,
                    'acceptedAnswers': [row.get('correctAnswer', '').strip()] if row.get('correctAnswer') else []
                })
        except Exception as e:
            return [], [{'id': 0, 'questionText': 'CSV Parse Error', 'errors': [f'Invalid CSV format: {str(e)}']}]

    # 3. WORD DOCX FORMAT
    elif filename.endswith('.docx'):
        try:
            doc = docx.Document(file_storage)
            parsed_from_tables = False

            # A) Check Word Tables
            if doc.tables:
                for t_idx, table in enumerate(doc.tables):
                    first_row = table.rows[0] if table.rows else None
                    if first_row and len(first_row.cells) == 2:
                        kv = {}
                        for row in table.rows:
                            if len(row.cells) >= 2:
                                k = row.cells[0].text.strip().lower()
                                v = row.cells[1].text.strip()
                                kv[k] = v

                        if any(k in kv for k in ['question', 'question text', 'type']):
                            parsed_from_tables = True
                            q_text = kv.get('question') or kv.get('question text') or ''
                            q_type = kv.get('type', 'mscq')
                            sel_type = kv.get('selection type', 'single')
                            raw_opts = kv.get('options', '')
                            options_list = []
                            if raw_opts:
                                for line in raw_opts.splitlines():
                                    line = line.strip()
                                    if not line: continue
                                    if '.' in line:
                                        letter, text = line.split('.', 1)
                                        options_list.append({'id': letter.strip().upper(), 'text': text.strip()})
                                    elif ')' in line:
                                        letter, text = line.split(')', 1)
                                        options_list.append({'id': letter.strip().upper(), 'text': text.strip()})
                                    elif ':' in line:
                                        letter, text = line.split(':', 1)
                                        options_list.append({'id': letter.strip().upper(), 'text': text.strip()})
                                    else:
                                        letter = chr(65 + len(options_list))
                                        options_list.append({'id': letter, 'text': line})

                            cs = kv.get('case sensitive', '').lower() in ['true', '1', 'yes']
                            raw_questions.append({
                                'id': t_idx + 1,
                                'type': q_type,
                                'selectionType': sel_type,
                                'questionText': q_text,
                                'options': options_list,
                                'correctAnswer': kv.get('correct answer', ''),
                                'marks': kv.get('marks', '1'),
                                'negativeMarks': kv.get('negative marks', '0.25'),
                                'explanation': kv.get('explanation', ''),
                                'caseSensitive': cs,
                                'acceptedAnswers': [kv.get('correct answer', '')] if kv.get('correct answer') else [],
                                'module': kv.get('module', '')
                            })
                    elif first_row and len(first_row.cells) >= 6:
                        parsed_from_tables = True
                        for r_idx, row in enumerate(table.rows):
                            if r_idx == 0: continue
                            cells = row.cells
                            if len(cells) >= 2 and cells[0].text.strip():
                                q_text = cells[0].text.strip()
                                opt_a = cells[1].text.strip() if len(cells) > 1 else ''
                                opt_b = cells[2].text.strip() if len(cells) > 2 else ''
                                opt_c = cells[3].text.strip() if len(cells) > 3 else ''
                                opt_d = cells[4].text.strip() if len(cells) > 4 else ''
                                corr = cells[5].text.strip().upper() if len(cells) > 5 else 'A'
                                marks_val = cells[6].text.strip() if len(cells) > 6 else '1'
                                opts = []
                                for ltr, txt in [('A', opt_a), ('B', opt_b), ('C', opt_c), ('D', opt_d)]:
                                    if txt: opts.append({'id': ltr, 'text': txt})
                                raw_questions.append({
                                    'id': r_idx,
                                    'type': 'mscq',
                                    'selectionType': 'single',
                                    'questionText': q_text,
                                    'options': opts,
                                    'correctAnswer': corr,
                                    'marks': marks_val,
                                    'negativeMarks': 0.25,
                                    'explanation': '',
                                    'caseSensitive': False,
                                    'acceptedAnswers': [corr],
                                    'module': 'Single Choice'
                                })

            # B) If no questions found in tables, parse Paragraphs (supports copy-pasted Question Repository text with tabs or colons)
            if not parsed_from_tables or len(raw_questions) == 0:
                current_q = None
                in_options = False

                for p in doc.paragraphs:
                    line = p.text.strip()
                    if not line:
                        continue

                    lower_line = line.lower()
                    if re.match(r'^(?:question\s+\d+|q\d+[:.]?)', lower_line):
                        if current_q and (current_q.get('questionText') or current_q.get('options')):
                            raw_questions.append(current_q)
                        current_q = {
                            'id': len(raw_questions) + 1,
                            'type': 'mscq',
                            'selectionType': 'single',
                            'questionText': '',
                            'options': [],
                            'correctAnswer': '',
                            'marks': '1',
                            'negativeMarks': '0.25',
                            'explanation': '',
                            'caseSensitive': False,
                            'acceptedAnswers': [],
                            'module': ''
                        }
                        in_options = False
                        continue

                    key = None
                    val = None
                    if '\t' in line:
                        parts = line.split('\t', 1)
                        key = parts[0].strip().lower()
                        val = parts[1].strip()
                    elif ':' in line and not (line.startswith('http://') or line.startswith('https://')):
                        parts = line.split(':', 1)
                        possible_key = parts[0].strip().lower()
                        if possible_key in ['type', 'selection type', 'question', 'options', 'correct answer', 'marks', 'negative marks', 'explanation', 'case sensitive', 'module']:
                            key = possible_key
                            val = parts[1].strip()

                    if key:
                        in_options = False
                        if current_q is None:
                            current_q = {
                                'id': len(raw_questions) + 1,
                                'type': 'mscq',
                                'selectionType': 'single',
                                'questionText': '',
                                'options': [],
                                'correctAnswer': '',
                                'marks': '1',
                                'negativeMarks': '0.25',
                                'explanation': '',
                                'caseSensitive': False,
                                'acceptedAnswers': [],
                                'module': ''
                            }

                        if key in ['type']:
                            current_q['type'] = val
                        elif key in ['selection type', 'selectiontype']:
                            current_q['selectionType'] = val
                        elif key in ['question', 'question text']:
                            current_q['questionText'] = val
                        elif key in ['correct answer', 'correctanswer', 'answer', 'correct']:
                            current_q['correctAnswer'] = val
                        elif key in ['marks', 'mark']:
                            current_q['marks'] = val
                        elif key in ['negative marks', 'negativemarks', 'neg marks']:
                            current_q['negativeMarks'] = val
                        elif key in ['explanation']:
                            current_q['explanation'] = val
                        elif key in ['case sensitive', 'casesensitive']:
                            current_q['caseSensitive'] = val.lower() in ['true', '1', 'yes']
                        elif key in ['module']:
                            current_q['module'] = val
                        elif key in ['options', 'option']:
                            in_options = True
                            if val:
                                opt_line = val.strip()
                                if '.' in opt_line:
                                    ltr, txt = opt_line.split('.', 1)
                                    current_q['options'].append({'id': ltr.strip().upper(), 'text': txt.strip()})
                                elif ')' in opt_line:
                                    ltr, txt = opt_line.split(')', 1)
                                    current_q['options'].append({'id': ltr.strip().upper(), 'text': txt.strip()})
                                else:
                                    current_q['options'].append({'id': chr(65 + len(current_q['options'])), 'text': opt_line})
                    elif in_options and current_q:
                        opt_line = line.strip()
                        if '.' in opt_line:
                            ltr, txt = opt_line.split('.', 1)
                            current_q['options'].append({'id': ltr.strip().upper(), 'text': txt.strip()})
                        elif ')' in opt_line:
                            ltr, txt = opt_line.split(')', 1)
                            current_q['options'].append({'id': ltr.strip().upper(), 'text': txt.strip()})
                        else:
                            current_q['options'].append({'id': chr(65 + len(current_q['options'])), 'text': opt_line})

                if current_q and (current_q.get('questionText') or current_q.get('options')):
                    raw_questions.append(current_q)
        except Exception as e:
            return [], [{'id': 0, 'questionText': 'DOCX Parse Error', 'errors': [f'Invalid Word DOCX format: {str(e)}']}]

    # STRICT VALIDATION FOR SUPPORTED QUESTION TYPES
    valid_questions = []
    invalid_questions = []

    MODULE_MAP = {
        'mscq_single': 'Single Choice',
        'mscq_multiple': 'Multiple Choice',
        'mscq_select': 'Select Dropdown',
        'fill_blank': 'Fill in the Blanks',
        'true_false': 'True / False',
        'coding': 'Coding'
    }

    for q in raw_questions:
        errors = []
        q_text = str(q.get('questionText', '')).strip()
        if not q_text:
            errors.append('Question statement is missing.')

        raw_type = str(q.get('type', '')).strip().lower()
        sel_type = str(q.get('selectionType', '')).strip().lower()

        norm_type = 'mscq_single'
        if raw_type in ['mscq', 'mscq_single']:
            if sel_type in ['multiple', 'mscq_multiple']:
                norm_type = 'mscq_multiple'
            elif sel_type in ['select', 'dropdown', 'mscq_select']:
                norm_type = 'mscq_select'
            else:
                norm_type = 'mscq_single'
        elif raw_type in ['fillintheblanks', 'fill_blank', 'fillInTheBlanks', 'blank', 'fib']:
            norm_type = 'fill_blank'
        elif raw_type in ['truefalse', 'true_false', 'trueFalse', 'tf', 'boolean']:
            norm_type = 'true_false'
        elif raw_type in ['coding', 'code']:
            norm_type = 'coding'
        else:
            errors.append(f"Invalid question type '{raw_type}'. Supported: mscq, fillInTheBlanks, trueFalse, coding.")

        try:
            marks = float(q.get('marks', 1))
            if marks < 0: errors.append('Marks must be greater than or equal to 0.')
        except (ValueError, TypeError):
            marks = 1.0
            errors.append('Marks must be numeric.')

        try:
            neg = float(q.get('negativeMarks', 0.25))
            if neg < 0: errors.append('Negative marks deduction must be greater than or equal to 0.')
        except (ValueError, TypeError):
            neg = 0.25
            errors.append('Negative marks must be numeric.')

        correct_ans = str(q.get('correctAnswer', '')).strip()
        opts = q.get('options', [])

        # Filter out empty options for fill_blank
        if norm_type == 'fill_blank':
            opts = [o for o in opts if isinstance(o, dict) and o.get('text', '').strip()]
            q['options'] = opts

        # True / False normalization
        if norm_type == 'true_false':
            if not opts or all(not o.get('text') for o in opts):
                opts = [{'id': 'A', 'text': 'True'}, {'id': 'B', 'text': 'False'}]
                q['options'] = opts
            if correct_ans in ['A', 'a', 'True', 'true', 'T', 't', '1']:
                correct_ans = 'True'
            elif correct_ans in ['B', 'b', 'False', 'false', 'F', 'f', '0']:
                correct_ans = 'False'
            q['correctAnswer'] = correct_ans
            q['acceptedAnswers'] = ['True', 'A'] if correct_ans == 'True' else ['False', 'B']

        if norm_type in ['mscq_single', 'mscq_select']:
            if len(opts) < 2:
                errors.append('At least two answer options are required.')
            if not correct_ans:
                errors.append('Correct answer option letter is required.')
        elif norm_type == 'mscq_multiple':
            if len(opts) < 2:
                errors.append('At least two answer options are required.')
            if not correct_ans:
                errors.append('At least one correct answer letter is required.')
        elif norm_type == 'fill_blank':
            if not correct_ans and not q.get('acceptedAnswers'):
                errors.append('Correct answer or accepted answers are required for Fill in the Blanks.')
        elif norm_type == 'true_false':
            if not correct_ans:
                errors.append('Correct answer (True or False) is required.')

        q_mod = (q.get('module') or '').strip()
        if not q_mod or q_mod.lower() == 'general':
            q_mod = MODULE_MAP.get(norm_type, 'General')

        q['question_type_norm'] = norm_type
        q['marks_norm'] = marks
        q['negative_marks_norm'] = neg
        q['question_text_norm'] = q_text
        q['module_norm'] = q_mod

        if errors:
            q['status'] = 'invalid'
            q['errors'] = errors
            invalid_questions.append(q)
        else:
            q['status'] = 'valid'
            q['errors'] = []
            valid_questions.append(q)

    return valid_questions, invalid_questions

# --- IMPORT PREVIEW API (Returns validation preview without saving) ---
@admin_bp.route('/api/questions/import_preview', methods=['POST'])
@require_admin_or_coordinator
def api_import_preview():
    file = request.files.get('file')
    if not file or file.filename == '':
        return jsonify({'success': False, 'error': 'No file uploaded.'}), 400

    filename = file.filename
    valid_q, invalid_q = parse_questions_from_file(file, filename)

    return jsonify({
        'success': True,
        'filename': filename,
        'summary': {
            'total': len(valid_q) + len(invalid_q),
            'valid': len(valid_q),
            'invalid': len(invalid_q)
        },
        'valid_questions': valid_q,
        'invalid_questions': invalid_q
    })

# --- IMPORT CONFIRM API (Saves confirmed questions from preview) ---
@admin_bp.route('/api/questions/import_confirm', methods=['POST'])
@require_admin_or_coordinator
def api_import_confirm():
    data = request.get_json() or {}
    quiz_id = data.get('quiz_id')
    questions = data.get('questions', [])

    if not quiz_id:
        return jsonify({'success': False, 'error': 'Target Assessment Session (quiz_id) is required.'}), 400
    if not questions:
        return jsonify({'success': False, 'error': 'No valid questions to import.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Database error.'}), 500

    imported_count = 0
    MODULE_MAP = {
        'mscq_single': 'Single Choice',
        'mscq_multiple': 'Multiple Choice',
        'mscq_select': 'Select Dropdown',
        'fill_blank': 'Fill in the Blanks',
        'true_false': 'True / False',
        'coding': 'Coding'
    }
    try:
        with conn.cursor() as cursor:
            for q in questions:
                q_text = q.get('question_text_norm') or q.get('questionText') or ''
                q_type = q.get('question_type_norm') or q.get('type') or 'mscq_single'
                marks = q.get('marks_norm', 1)
                neg = q.get('negative_marks_norm', 0.25)
                explanation = q.get('explanation', '')
                correct_ans = q.get('correctAnswer', '')
                options = q.get('options', [])
                mod_name = q.get('module_norm') or q.get('module') or MODULE_MAP.get(q_type, 'General')

                meta = {
                    'options': options,
                    'correctAnswer': correct_ans,
                    'negativeMarks': neg,
                    'caseSensitive': bool(q.get('caseSensitive', False)),
                    'acceptedAnswers': q.get('acceptedAnswers') or [correct_ans]
                }

                opt_a = options[0].get('text', '') if len(options) > 0 else ''
                opt_b = options[1].get('text', '') if len(options) > 1 else ''
                opt_c = options[2].get('text', '') if len(options) > 2 else ''
                opt_d = options[3].get('text', '') if len(options) > 3 else ''

                cursor.execute('''
                    INSERT INTO Questions
                        (quiz_id, question_type, question_text,
                         option_a, option_b, option_c, option_d,
                         correct_option, marks, module, subject,
                         difficulty, status, explanation,
                         negative_marks, metadata_json)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ''', (
                    quiz_id, q_type, q_text,
                    opt_a, opt_b, opt_c, opt_d,
                    correct_ans, marks, mod_name, 'General',
                    'Medium', 'Published', explanation,
                    neg, json.dumps(meta)
                ))
                imported_count += 1
            conn.commit()
            return jsonify({
                'success': True,
                'count': imported_count,
                'message': f"Successfully imported {imported_count} questions."
            })
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

# --- DOWNLOAD SAMPLE TEMPLATES (JSON, CSV, DOCX) ---
@admin_bp.route('/api/questions/sample/<fmt>', methods=['GET'])
@require_admin_or_coordinator
def api_download_sample(fmt):
    fmt = fmt.lower()
    sample_files = {
        'json': ('sample_questions.json', 'application/json'),
        'csv': ('sample_questions.csv', 'text/csv'),
        'docx': ('sample_questions.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    }

    if fmt not in sample_files:
        return jsonify({'error': 'Invalid format requested. Choose json, csv, or docx.'}), 400

    filename, mimetype = sample_files[fmt]
    filepath = os.path.join(current_app.root_path, 'static', 'samples', filename)

    if not os.path.exists(filepath):
        # Regenerate sample files if missing
        import scripts.generate_samples as gs
        gs.generate_samples()

    return send_file(filepath, mimetype=mimetype, as_attachment=True, download_name=filename)

# --- EXPORT QUESTIONS (JSON or CSV matching required schema) ---
@admin_bp.route('/api/questions/export', methods=['GET'])
@require_admin_or_coordinator
def api_export_questions():
    fmt = request.args.get('format', 'json').lower()
    quiz_id = request.args.get('quiz_id')
    selected_ids = request.args.get('ids', '')

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'DB Error'}), 500
    try:
        with conn.cursor() as cursor:
            query = 'SELECT * FROM Questions WHERE 1=1'
            params = []
            if quiz_id and quiz_id != 'all':
                query += ' AND quiz_id=%s'
                params.append(quiz_id)
            if selected_ids:
                ids = [i.strip() for i in selected_ids.split(',') if i.strip()]
                if ids:
                    format_strings = ','.join(['%s'] * len(ids))
                    query += f' AND question_id IN ({format_strings})'
                    params.extend(ids)

            query += ' ORDER BY question_id DESC'
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()

            export_data = []
            for r in rows:
                meta = {}
                if r.get('metadata_json'):
                    try: meta = json.loads(r['metadata_json'])
                    except Exception: meta = {}

                # Map to standard schema
                q_type = r.get('question_type', 'mscq_single')
                sel_type = meta.get('selectionType', 'single')
                if q_type == 'mscq_single':
                    exp_type = 'mscq'
                    sel_type = 'single'
                elif q_type == 'mscq_multiple':
                    exp_type = 'mscq'
                    sel_type = 'multiple'
                elif q_type == 'mscq_select':
                    exp_type = 'mscq'
                    sel_type = 'select'
                elif q_type == 'fill_blank':
                    exp_type = 'fillInTheBlanks'
                    sel_type = 'N/A'
                elif q_type == 'true_false':
                    exp_type = 'trueFalse'
                    sel_type = 'N/A'
                else:
                    exp_type = 'mscq'
                    sel_type = 'single'

                export_data.append({
                    'id': r.get('question_id'),
                    'type': exp_type,
                    'selectionType': sel_type,
                    'questionText': r.get('question_text', ''),
                    'options': meta.get('options') or [
                        {'id': 'A', 'text': r.get('option_a', '')},
                        {'id': 'B', 'text': r.get('option_b', '')},
                        {'id': 'C', 'text': r.get('option_c', '')},
                        {'id': 'D', 'text': r.get('option_d', '')}
                    ],
                    'correctAnswer': meta.get('correctAnswer') or r.get('correct_option', ''),
                    'marks': r.get('marks', 1),
                    'negativeMarks': r.get('negative_marks', 0.25),
                    'explanation': r.get('explanation', ''),
                    'caseSensitive': meta.get('caseSensitive', False)
                })

            if fmt == 'csv':
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(['id', 'type', 'selectionType', 'questionText', 'options', 'correctAnswer', 'marks', 'negativeMarks', 'explanation', 'caseSensitive'])
                for item in export_data:
                    opts_str = ' | '.join([f"{o.get('id', '')}. {o.get('text', '')}" for o in item['options']])
                    writer.writerow([
                        item['id'], item['type'], item['selectionType'],
                        item['questionText'], opts_str, item['correctAnswer'],
                        item['marks'], item['negativeMarks'], item['explanation'],
                        str(item['caseSensitive']).lower()
                    ])
                return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=questions_export.csv'})
            elif fmt in ['docx', 'word']:
                doc = docx.Document()
                title_p = doc.add_heading('QuizMaster – Question Repository Export', level=0)
                intro_p = doc.add_paragraph(f'Exported {len(export_data)} questions from QuizMaster Question Repository.')
                intro_p.runs[0].font.italic = True

                for idx, q in enumerate(export_data):
                    doc.add_heading(f"Question {idx + 1}", level=2)
                    opts_str = '\n'.join([f"{o.get('id', '')}. {o.get('text', '')}" for o in q.get('options', [])])
                    rows_data = [
                        ("Type", q.get('type', 'mscq')),
                        ("Selection Type", q.get('selectionType', 'single')),
                        ("Question", q.get('questionText', '')),
                        ("Options", opts_str),
                        ("Correct Answer", str(q.get('correctAnswer', ''))),
                        ("Marks", str(q.get('marks', 1))),
                        ("Negative Marks", str(q.get('negativeMarks', 0.25))),
                        ("Explanation", q.get('explanation', '')),
                        ("Case Sensitive", str(q.get('caseSensitive', False)).lower())
                    ]
                    table = doc.add_table(rows=len(rows_data), cols=2)
                    table.alignment = docx.enum.table.WD_TABLE_ALIGNMENT.CENTER
                    table.style = 'Light Shading Accent 1' if 'Light Shading Accent 1' in [s.name for s in doc.styles] else 'Table Grid'
                    for r_idx, (k, v) in enumerate(rows_data):
                        c0 = table.cell(r_idx, 0)
                        c1 = table.cell(r_idx, 1)
                        c0.text = k
                        c1.text = str(v)
                        c0.paragraphs[0].runs[0].font.bold = True
                        c0.width = docx.shared.Inches(1.8)

                bio = io.BytesIO()
                doc.save(bio)
                bio.seek(0)
                return send_file(
                    bio,
                    mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    as_attachment=True,
                    download_name='questions_export.docx'
                )
            else:
                return Response(json.dumps(export_data, default=str, indent=2), mimetype='application/json', headers={'Content-Disposition': 'attachment; filename=questions_export.json'})
    finally:
        conn.close()

@admin_bp.route('/question_bank/api/get/<int:question_id>')
@require_admin_or_coordinator
def api_get_question(question_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Database connection error'}), 500
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT q.*, COALESCE(z.title, 'General') as session_name FROM Questions q LEFT JOIN Quizzes z ON q.quiz_id = z.quiz_id WHERE q.question_id=%s", (question_id,))
            q = cursor.fetchone()
            if not q:
                return jsonify({'success': False, 'error': 'Question not found'}), 404
            meta = {}
            if q.get('metadata_json'):
                try: meta = json.loads(q['metadata_json'])
                except Exception: pass
            q['meta'] = meta
            return jsonify({'success': True, 'question': q})
    finally:
        conn.close()

@admin_bp.route('/api/questions/upload_media', methods=['POST'])
@admin_bp.route('/question_bank/upload_media', methods=['POST'])
@require_admin_or_coordinator
def upload_question_media():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400
    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    
    allowed_exts = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed_exts:
        return jsonify({'success': False, 'error': f'Unsupported image format .{ext}'}), 400
    
    import secrets
    safe_name = f"qimg_{secrets.token_hex(8)}.{ext}"
    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'questions')
    try:
        os.makedirs(upload_dir, exist_ok=True)
        target_path = os.path.join(upload_dir, safe_name)
        file.save(target_path)
        url = f"/static/uploads/questions/{safe_name}"
        return jsonify({'success': True, 'url': url, 'filename': safe_name})
    except Exception as e:
        import base64
        file.seek(0)
        content = file.read()
        mime = f"image/{'svg+xml' if ext=='svg' else ext}"
        b64 = base64.b64encode(content).decode('utf-8')
        data_url = f"data:{mime};base64,{b64}"
        return jsonify({'success': True, 'url': data_url, 'filename': safe_name, 'is_data_url': True})

@admin_bp.route('/question_bank/duplicate/<int:question_id>', methods=['POST', 'GET'])
@require_admin_or_coordinator
def duplicate_question_bank(question_id):
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM Questions WHERE question_id=%s', (question_id,))
                q = cursor.fetchone()
                if q:
                    cursor.execute('''
                        INSERT INTO Questions
                            (quiz_id, question_type, question_text,
                             option_a, option_b, option_c, option_d,
                             correct_option, marks, module, subject,
                             difficulty, status, explanation,
                             negative_marks, metadata_json)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ''', (
                        q['quiz_id'], q['question_type'], f"{q['question_text']} (Copy)",
                        q['option_a'], q['option_b'], q['option_c'], q['option_d'],
                        q['correct_option'], q['marks'], q.get('module', 'General'), q.get('subject', 'General'),
                        q.get('difficulty', 'Medium'), 'Draft', q.get('explanation', ''),
                        q.get('negative_marks', 0.25), q.get('metadata_json')
                    ))
                    conn.commit()
                    flash('Question duplicated as Draft!', 'success')
        except Exception as e:
            conn.rollback()
            flash(f'Error duplicating question: {str(e)}', 'error')
        finally:
            conn.close()
    return redirect('/admin/content')

@admin_bp.route('/question_bank/delete/<int:question_id>', methods=['POST', 'GET'])
@require_admin_or_coordinator
def delete_question_bank(question_id):
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute('DELETE FROM Questions WHERE question_id=%s', (question_id,))
                conn.commit()
                flash('Question deleted successfully.', 'success')
        except Exception as e:
            conn.rollback()
            flash(f'Error deleting question: {str(e)}', 'error')
        finally:
            conn.close()
    return redirect('/admin/content')

@admin_bp.route('/question_bank/delete_bulk', methods=['POST'])
@require_admin_or_coordinator
def delete_bulk_question_bank():
    q_ids = request.form.getlist('q_ids')
    if not q_ids and request.is_json:
        data = request.get_json() or {}
        q_ids = data.get('q_ids', [])
    if q_ids:
        conn = get_db_connection()
        if conn:
            try:
                with conn.cursor() as cursor:
                    format_strings = ','.join(['%s'] * len(q_ids))
                    cursor.execute(f'DELETE FROM Questions WHERE question_id IN ({format_strings})', tuple(q_ids))
                    conn.commit()
                    if request.is_json:
                        return jsonify({'success': True, 'message': f'Deleted {len(q_ids)} questions.'})
                    flash(f'Successfully deleted {len(q_ids)} questions.', 'success')
            except Exception as e:
                conn.rollback()
                if request.is_json:
                    return jsonify({'success': False, 'error': str(e)}), 500
                flash(f'Error deleting questions: {str(e)}', 'error')
            finally:
                conn.close()
    return redirect('/admin/content')

@admin_bp.route('/api/questions/bulk_status', methods=['POST'])
@require_admin_or_coordinator
def api_bulk_status_question():
    data = request.get_json() or {}
    q_ids = data.get('q_ids', [])
    new_status = data.get('status', 'Published')
    if not q_ids:
        return jsonify({'success': False, 'error': 'No questions selected'}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Database error'}), 500
    try:
        with conn.cursor() as cursor:
            format_strings = ','.join(['%s'] * len(q_ids))
            params = [new_status] + list(q_ids)
            cursor.execute(f'UPDATE Questions SET status=%s WHERE question_id IN ({format_strings})', tuple(params))
            conn.commit()
            return jsonify({'success': True, 'message': f'Updated {len(q_ids)} questions to {new_status}.'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@admin_bp.route('/api/questions/upload_media', methods=['POST'])
@require_admin_or_coordinator
def api_upload_question_media():
    file = request.files.get('media_file')
    if not file or file.filename == '':
        return jsonify({'success': False, 'error': 'No media file provided'}), 400
    
    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'questions')
    os.makedirs(upload_dir, exist_ok=True)
    
    safe_name = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
    final_name = timestamp + safe_name
    dest_path = os.path.join(upload_dir, final_name)
    file.save(dest_path)
    
    file_url = f'/static/uploads/questions/{final_name}'
    return jsonify({'success': True, 'url': file_url, 'filename': final_name})

DEFAULT_ADVANCE_SETTINGS = {
    'enable_negative_marking': True,
    'default_marks': 1.0,
    'default_negative_marks': 0.25,
    'allow_individual_negative': True,
    'allow_partial_marking': True,
    'restrict_min_score_zero': True,
    'fill_blank_case_sensitive': True,
    'fill_blank_trim_whitespace': True,
    'fill_blank_ignore_punctuation': True,
    'fill_blank_accept_multiple': True,
    'randomize_options': True
}

@admin_bp.route('/api/advance_settings', methods=['GET', 'POST'])
@require_admin_or_coordinator
def api_advance_settings():
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'error': 'Database error'}), 500
    try:
        with conn.cursor() as cursor:
            if request.method == 'POST':
                data = request.get_json() or {}
                cursor.execute('''
                    INSERT INTO System_Settings (setting_key, setting_value)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE setting_value=%s
                ''', ('advance_question_settings', json.dumps(data), json.dumps(data)))
                conn.commit()
                return jsonify({'success': True, 'message': 'Advanced settings saved successfully!', 'settings': data})
            else:
                cursor.execute('SELECT setting_value FROM System_Settings WHERE setting_key=%s', ('advance_question_settings',))
                row = cursor.fetchone()
                settings = DEFAULT_ADVANCE_SETTINGS.copy()
                if row and row.get('setting_value'):
                    try:
                        saved = json.loads(row['setting_value'])
                        settings.update(saved)
                    except Exception:
                        pass
                return jsonify({'success': True, 'settings': settings})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

# ==============================================================================
# ADMIN SETTINGS & OFFICIAL ASSET MANAGEMENT
# ==============================================================================
from official_assets_manager import (
    upload_official_asset, get_official_assets, get_active_official_asset,
    set_official_asset_active, delete_official_asset, log_admin_action
)
from user_management_service import (
    create_single_user, create_bulk_users_manual, generate_csv_template,
    parse_and_validate_csv, execute_csv_import, generate_error_csv,
    get_users_directory, reset_user_temp_password, force_user_password_change,
    ALLOWED_DEPARTMENTS, ALLOWED_ROLES, ALLOWED_SECTIONS, ALLOWED_YEARS
)

@admin_bp.route('/settings')
@admin_bp.route('/settings/general')
@require_admin
def admin_settings_general():
    conn = get_db_connection()
    batches = []
    stats = {'signatures': 0, 'seals': 0, 'users': 0, 'temp_passwords': 0}
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as cnt FROM official_assets WHERE asset_type='program_director_signature'")
                stats['signatures'] = cursor.fetchone()['cnt']
                cursor.execute("SELECT COUNT(*) as cnt FROM official_assets WHERE asset_type='official_seal'")
                stats['seals'] = cursor.fetchone()['cnt']
                cursor.execute("SELECT COUNT(*) as cnt FROM Users")
                stats['users'] = cursor.fetchone()['cnt']
                cursor.execute("SELECT COUNT(*) as cnt FROM Users WHERE must_change_password=1")
                stats['temp_passwords'] = cursor.fetchone()['cnt']
                cursor.execute("SELECT batch_name as batch FROM Batches ORDER BY batch_name DESC")
                batches = cursor.fetchall()
        finally:
            conn.close()
    return render_template('admin_settings_general.html', stats=stats, batches=batches)

@admin_bp.route('/settings/assets')
@require_admin
def admin_settings_assets():
    signatures = get_official_assets('program_director_signature')
    seals = get_official_assets('official_seal')
    active_sig = get_active_official_asset('program_director_signature')
    active_seal = get_active_official_asset('official_seal')
    return render_template(
        'admin_settings_assets.html',
        signatures=signatures,
        seals=seals,
        active_sig=active_sig,
        active_seal=active_seal
    )

@admin_bp.route('/settings/users')
@require_admin
def admin_settings_users():
    conn = get_db_connection()
    batches = []
    depts = list(ALLOWED_DEPARTMENTS)
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT batch_name as batch FROM Batches ORDER BY batch_name DESC")
                batches = cursor.fetchall()
                try:
                    cursor.execute("SELECT DISTINCT department FROM Users WHERE department IS NOT NULL AND department != ''")
                    for d in cursor.fetchall():
                        val = d['department'].strip()
                        if val and val not in depts:
                            depts.append(val)
                except Exception:
                    pass
        finally:
            conn.close()

    return render_template(
        'admin_settings_users.html',
        batches=batches,
        departments=sorted(depts),
        roles=ALLOWED_ROLES,
        sections=ALLOWED_SECTIONS,
        years=ALLOWED_YEARS
    )

# --- Asset API Endpoints ---
@admin_bp.route('/api/assets', methods=['GET'])
@require_admin
def api_get_assets():
    asset_type = request.args.get('type')
    assets = get_official_assets(asset_type)
    return jsonify({'success': True, 'assets': assets})

@admin_bp.route('/api/assets/upload', methods=['POST'])
@require_admin
def api_upload_asset():
    asset_type = request.form.get('asset_type')
    file = request.files.get('file')
    auto_activate = request.form.get('auto_activate', 'true').lower() in ('true', '1', 'yes')
    admin_id = session.get('user_id')

    if not file:
        return jsonify({'success': False, 'message': 'No file uploaded.'}), 400

    result = upload_official_asset(asset_type, file, uploaded_by=admin_id, req=request, auto_activate=auto_activate)
    status_code = 200 if result['success'] else 400
    return jsonify(result), status_code

@admin_bp.route('/api/assets/<int:asset_id>/status', methods=['PATCH', 'POST'])
@require_admin
def api_toggle_asset_status(asset_id):
    data = request.get_json() or request.form or {}
    is_active = int(data.get('is_active', 1))
    admin_id = session.get('user_id')

    result = set_official_asset_active(asset_id, is_active, admin_user_id=admin_id, req=request)
    status_code = 200 if result['success'] else 400
    return jsonify(result), status_code

@admin_bp.route('/api/assets/<int:asset_id>', methods=['DELETE', 'POST'])
@require_admin
def api_delete_asset(asset_id):
    admin_id = session.get('user_id')
    result = delete_official_asset(asset_id, admin_user_id=admin_id, req=request)
    status_code = 200 if result['success'] else 400
    return jsonify(result), status_code

# --- User Management API Endpoints ---
@admin_bp.route('/api/users/list', methods=['GET'])
@require_admin
def api_get_users_list():
    search = request.args.get('search', '').strip()
    role = request.args.get('role', '').strip()
    department = request.args.get('department', '').strip()
    session_name = request.args.get('session', '').strip()
    status = request.args.get('status', '').strip()
    must_change_pw = request.args.get('must_change_password', '').strip()
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))

    data = get_users_directory(
        search=search, role=role, department=department,
        session_name=session_name, status=status,
        must_change_pw=must_change_pw, page=page, per_page=per_page
    )
    return jsonify({'success': True, **data})

@admin_bp.route('/api/users/create-single', methods=['POST'])
@require_admin
def api_create_single_user():
    data = request.get_json() or request.form.to_dict()
    admin_id = session.get('user_id')
    result = create_single_user(data, admin_id=admin_id, req=request)
    status_code = 200 if result['success'] else 400
    return jsonify(result), status_code

@admin_bp.route('/api/users/create-bulk', methods=['POST'])
@require_admin
def api_create_bulk_users():
    payload = request.get_json() or {}
    users_list = payload.get('users', [])
    admin_id = session.get('user_id')
    result = create_bulk_users_manual(users_list, admin_id=admin_id, req=request)
    status_code = 200 if result['success'] else 400
    return jsonify(result), status_code

@admin_bp.route('/api/users/csv-template', methods=['GET'])
@require_admin
def api_download_csv_template():
    csv_text = generate_csv_template()
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment;filename=quizmaster_bulk_users_template.csv"}
    )

@admin_bp.route('/api/users/validate-csv', methods=['POST'])
@require_admin
def api_validate_csv():
    file = request.files.get('file')
    if not file:
        return jsonify({'success': False, 'message': 'No CSV file uploaded.'}), 400
    result = parse_and_validate_csv(file)
    status_code = 200 if result['success'] else 400
    return jsonify(result), status_code

@admin_bp.route('/api/users/import-csv', methods=['POST'])
@require_admin
def api_import_csv():
    payload = request.get_json() or {}
    preview_data = payload.get('preview_data', [])
    admin_id = session.get('user_id')
    result = execute_csv_import(preview_data, admin_id=admin_id, req=request)
    status_code = 200 if result['success'] else 400
    return jsonify(result), status_code

@admin_bp.route('/api/users/export-errors', methods=['POST'])
@require_admin
def api_export_csv_errors():
    payload = request.get_json() or {}
    failed_rows = payload.get('failed_rows', [])
    csv_text = generate_error_csv(failed_rows)
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment;filename=import_errors.csv"}
    )

@admin_bp.route('/api/users/<int:user_id>/status', methods=['PATCH', 'POST'])
@require_admin
def api_toggle_user_status(user_id):
    data = request.get_json() or request.form or {}
    is_blocked = int(data.get('is_blocked', 0))
    admin_id = session.get('user_id')
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE Users SET is_blocked=%s WHERE user_id=%s", (is_blocked, user_id))
        conn.commit()
        log_admin_action(admin_id, 'USER_STATUS_CHANGE', {'user_id': user_id, 'is_blocked': is_blocked}, request)
        return jsonify({'success': True, 'message': f"User account {'blocked' if is_blocked else 'unblocked'} successfully.", 'is_blocked': is_blocked})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()

@admin_bp.route('/api/users/<int:user_id>/reset-temp-password', methods=['POST'])
@require_admin
def api_reset_user_temp_password(user_id):
    admin_id = session.get('user_id')
    result = reset_user_temp_password(user_id, admin_id=admin_id, req=request)
    status_code = 200 if result['success'] else 400
    return jsonify(result), status_code

@admin_bp.route('/api/users/<int:user_id>/force-password-change', methods=['POST'])
@require_admin
def api_force_user_password_change(user_id):
    admin_id = session.get('user_id')
    result = force_user_password_change(user_id, admin_id=admin_id, req=request)
    status_code = 200 if result['success'] else 400
    return jsonify(result), status_code

@admin_bp.route('/api/users/<int:user_id>', methods=['DELETE'])
@require_admin
def api_delete_user_account(user_id):
    admin_id = session.get('user_id')
    if user_id == admin_id:
        return jsonify({'success': False, 'message': 'You cannot delete your own admin account.'}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({'success': False, 'message': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT full_name, email FROM Users WHERE user_id=%s", (user_id,))
            u = cursor.fetchone()
            if not u:
                return jsonify({'success': False, 'message': 'User not found'}), 404
            cursor.execute("DELETE FROM Users WHERE user_id=%s", (user_id,))
        conn.commit()
        log_admin_action(admin_id, 'USER_DELETE', {'user_id': user_id, 'email': u['email']}, request)
        return jsonify({'success': True, 'message': f"User {u['full_name']} deleted successfully."})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()



