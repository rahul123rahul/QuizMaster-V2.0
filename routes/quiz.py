from flask import Blueprint, request, redirect, render_template, jsonify, flash, session, send_file
from utils import get_db_connection
from datetime import datetime, timedelta
from certificate_generator import generate_certificate_pdf
import random

quiz_bp = Blueprint('quiz', __name__, template_folder='../templates')

def _stable_shuffle(items, seed_value):
    shuffled = list(items)
    rng = random.Random(str(seed_value))
    rng.shuffle(shuffled)
    return shuffled

def calculate_computed_semester(user_semester=None):
    """Calculate semester: if user has manual override, use that; otherwise calculate dynamically"""
    if user_semester:
        return user_semester
    
    # Auto-calculate based on current month
    # July-Dec = I (Odd), Jan-June = II (Even)
    month = datetime.now().month
    if 6 <= month <= 11:
        return 'I'
    else:
        return 'II'

@quiz_bp.route('/student/menu-spec')
def student_menu_spec():
    return render_template('student_menu_spec.html')

@quiz_bp.route('/student')
def student_dashboard():
    if session.get('role') != 'Student':
        return redirect('/')
    
    conn = get_db_connection()
    user_info = None
    center_info = None
    available = []
    history = []
    msg = None

    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT u.*, c.center_name, c.address, c.city 
                    FROM Users u 
                    LEFT JOIN Exam_Centers c ON u.allotted_center_id = c.center_id 
                    WHERE u.user_id=%s
                ''', (session['user_id'],))
                user_info = cursor.fetchone()

                now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)

                if user_info and user_info.get('enrolled_session'):
                    try:
                        u_sec = user_info.get('section') or ''
                        cursor.execute('''
                            SELECT z.*, 
                                   (SELECT COUNT(*) FROM Questions q WHERE q.quiz_id = z.quiz_id) as q_count,
                                   (SELECT COALESCE(SUM(marks), 0) FROM Questions q WHERE q.quiz_id = z.quiz_id) as real_marks
                            FROM Quizzes z 
                            WHERE batch=%s 
                            AND year=%s
                            AND (
                                (section IS NOT NULL AND section != '' AND section != 'All' AND FIND_IN_SET(%s, department) > 0 AND section = %s)
                                OR (
                                    (section IS NULL OR section = '' OR section = 'All')
                                    AND (FIND_IN_SET(%s, department) > 0 OR FIND_IN_SET(CONCAT(%s, ':', %s), department) > 0)
                                )
                            )
                            ORDER BY start_time ASC
                        ''', (user_info['enrolled_session'], user_info['study_year'], user_info['department'], u_sec, user_info['department'], user_info['department'], u_sec))
                    except Exception as e:
                        if 'Unknown column' in str(e):
                            cursor.execute('''
                                SELECT z.*, 
                                       (SELECT COUNT(*) FROM Questions q WHERE q.quiz_id = z.quiz_id) as q_count,
                                       (SELECT COALESCE(SUM(marks), 0) FROM Questions q WHERE q.quiz_id = z.quiz_id) as real_marks
                                FROM Quizzes z 
                                WHERE batch=%s AND FIND_IN_SET(%s, department) AND year=%s
                                ORDER BY start_time ASC
                            ''', (user_info['enrolled_session'], user_info['department'], user_info['study_year']))
                        else:
                            raise e
                else:
                    cursor.execute('SELECT * FROM Quizzes WHERE 1=0')

                quizzes = cursor.fetchall()

                for q in quizzes:
                    if isinstance(q['start_time'], str):
                        try:
                            dt = datetime.strptime(q['start_time'], '%Y-%m-%d %H:%M:%S')
                        except:
                            dt = datetime.strptime(q['start_time'].replace('T', ' '), '%Y-%m-%d %H:%M')
                    else:
                        dt = q['start_time']

                    q['display_time'] = dt.strftime('%d-%b %I:%M %p')
                    diff = (dt - now_ist).total_seconds()

                    if diff <= 0:
                        end = dt + timedelta(minutes=q['duration_minutes'])
                        late_cutoff = dt + timedelta(minutes=10)

                        if now_ist > end:
                            q.update({'is_locked': True, 'time_msg': 'Expired', 'seconds_left': 0})
                        elif now_ist > late_cutoff:
                            q.update({'is_locked': True, 'time_msg': 'Entry Closed', 'seconds_left': 0})
                        else:
                            q.update({'is_locked': False, 'time_msg': 'Live Now', 'seconds_left': 0})
                    else:
                        display_time = q['display_time']
                        q.update({'is_locked': True, 'time_msg': f'Starts: {display_time}', 'seconds_left': int(diff)})

                    q['instructions'] = (q.get('instructions') or 'Standard Rules.').replace('`', chr(39)).replace('&quot;', chr(34))
                    available.append(q)

                cursor.execute('''
                    SELECT q.title, q.total_marks, a.total_score, a.status, a.attempt_id, a.certificate_approved 
                    FROM Quiz_Attempts a 
                    JOIN Quizzes q ON a.quiz_id=q.quiz_id 
                    WHERE a.user_id=%s 
                    ORDER BY a.attempt_id DESC
                ''', (session['user_id'],))
                history = cursor.fetchall()

                cursor.execute('SELECT * FROM Announcements WHERE id=1')
                ann = cursor.fetchone()
                msg = ann['message'] if (ann and ann['is_active']) else None
        finally:
            conn.close()

    return render_template('student_dashboard.html', 
                          user=user_info, center=user_info, 
                          quizzes=available, history=history, 
                          winner_announce=msg,
                          user_full_name=user_info.get('full_name') if user_info else 'Student',
                          user_email=user_info.get('email') if user_info else None,
                          user_department=user_info.get('department') if user_info else None,
                          user_study_year=user_info.get('study_year') if user_info else None,
                          user_semester=user_info.get('semester') if user_info else None,
                          user_profile_image=user_info.get('avatar') if user_info else None,
                          computed_semester=calculate_computed_semester(user_info.get('semester') if user_info else None))

@quiz_bp.route('/student/progress')
def student_progress():
    if session.get('role') != 'Student':
        return redirect('/')
    
    conn = get_db_connection()
    user_info = None
    activities = []
    resumed_exams = []
    certificates = []
    
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM Users WHERE user_id=%s', (session['user_id'],))
                user_info = cursor.fetchone()
                
                cursor.execute('''
                    SELECT q.title, a.attempt_id, a.total_score, a.status, a.start_time, a.end_time, a.certificate_approved,
                           (SELECT COUNT(*) FROM Questions WHERE quiz_id=a.quiz_id) as total_questions,
                           (SELECT COUNT(*) FROM Quiz_Responses WHERE attempt_id=a.attempt_id AND selected_option IS NOT NULL) as answered
                    FROM Quiz_Attempts a 
                    JOIN Quizzes q ON a.quiz_id=q.quiz_id 
                    WHERE a.user_id=%s 
                    ORDER BY a.start_time DESC
                    LIMIT 20
                ''', (session['user_id'],))
                all_attempts = cursor.fetchall()
                
                for attempt in all_attempts:
                    if attempt['status'] == 'In-Progress':
                        resumed_exams.append(attempt)
                    elif attempt['status'] in ('Completed', 'Terminated'):
                        if attempt['certificate_approved']:
                            attempt['has_certificate'] = True
                        certificates.append(attempt)
                    activities.append(attempt)
        finally:
            conn.close()
    
    return render_template('student_progress.html',
                          user=user_info,
                          activities=activities,
                          resumed_exams=resumed_exams,
                          certificates=certificates,
                          user_full_name=user_info['full_name'] if user_info else 'Student',
                          user_email=user_info.get('email') if user_info else None,
                          user_department=user_info.get('department') if user_info else None,
                          user_study_year=user_info.get('study_year') if user_info else None,
                          user_semester=user_info.get('semester') if user_info else None,
                          user_profile_image=user_info.get('avatar') if user_info else None,
                          computed_semester=calculate_computed_semester(user_info.get('semester') if user_info else None))

@quiz_bp.route('/download/cert/<int:attempt_id>')
def download_certificate(attempt_id):
    if session.get('role') != 'Student':
        return redirect('/')

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT a.attempt_id, a.total_score, a.certificate_approved, a.user_id,
                       q.title, u.full_name
                FROM Quiz_Attempts a
                JOIN Quizzes q ON a.quiz_id = q.quiz_id
                JOIN Users u ON a.user_id = u.user_id
                WHERE a.attempt_id=%s AND a.user_id=%s
            ''', (attempt_id, session['user_id']))
            attempt = cursor.fetchone()
    finally:
        conn.close()

    if not attempt:
        return 'Attempt not found', 404

    if not attempt.get('certificate_approved'):
        return 'Certificate not available', 403

    cert_date = datetime.now().strftime('%Y-%m-%d')
    pdf_buffer = generate_certificate_pdf(
        attempt['full_name'],
        attempt['title'],
        attempt['total_score'],
        cert_date,
        attempt_id=attempt['attempt_id']
    )
    safe_title = ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in attempt['title']).strip() or 'certificate'
    filename = f"{safe_title}_{attempt['attempt_id']}.pdf"
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )

@quiz_bp.route('/download_certificate/<int:attempt_id>')
def download_certificate_public(attempt_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT a.attempt_id, a.total_score, a.certificate_approved,
                       q.title, u.full_name
                FROM Quiz_Attempts a
                JOIN Quizzes q ON a.quiz_id = q.quiz_id
                JOIN Users u ON a.user_id = u.user_id
                WHERE a.attempt_id=%s
            ''', (attempt_id,))
            attempt = cursor.fetchone()
    finally:
        conn.close()

    if not attempt:
        return 'Certificate not found', 404

    if not attempt.get('certificate_approved'):
        return 'Certificate not available', 403

    cert_date = datetime.now().strftime('%Y-%m-%d')
    pdf_buffer = generate_certificate_pdf(
        attempt['full_name'],
        attempt['title'],
        attempt['total_score'],
        cert_date,
        attempt_id=attempt['attempt_id']
    )
    safe_title = ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in attempt['title']).strip() or 'certificate'
    filename = f"{safe_title}_{attempt['attempt_id']}.pdf"
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )

@quiz_bp.route('/verify/<int:attempt_id>')
def verify_certificate(attempt_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT a.attempt_id, a.total_score, a.certificate_approved,
                       COALESCE(a.submitted_at, a.end_time, a.start_time) AS issued_at,
                       q.title, u.full_name
                FROM Quiz_Attempts a
                JOIN Quizzes q ON a.quiz_id = q.quiz_id
                JOIN Users u ON a.user_id = u.user_id
                WHERE a.attempt_id=%s
            ''', (attempt_id,))
            attempt = cursor.fetchone()
    finally:
        conn.close()

    if not attempt or not attempt.get('certificate_approved'):
        return 'Certificate not found in database', 404

    issued_at = attempt.get('issued_at')
    if hasattr(issued_at, 'strftime'):
        issued_at = issued_at.strftime('%Y-%m-%d %H:%M:%S')
    elif not issued_at:
        issued_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    data = {
        'full_name': attempt['full_name'],
        'title': attempt['title'],
        'total_score': attempt['total_score'],
        'timestamp': issued_at
    }
    return render_template('verify.html', data=data, attempt_id=attempt_id)

@quiz_bp.route('/quiz/<int:quiz_id>')
def quiz_interface(quiz_id):
    if 'user_id' not in session:
        return redirect('/')

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT full_name, department, study_year FROM Users WHERE user_id=%s', (session['user_id'],))
            user_info = cursor.fetchone()

            cursor.execute('SELECT * FROM Quizzes WHERE quiz_id=%s', (quiz_id,))
            meta = cursor.fetchone()
            if not meta:
                return 'Error: Quiz Not Found'

            cursor.execute('SELECT attempt_id, status FROM Quiz_Attempts WHERE user_id=%s AND quiz_id=%s', (session['user_id'], quiz_id))
            existing = cursor.fetchone()

            if existing:
                if existing['status'] != 'In-Progress':
                    flash('Already attempted. If any query contact to coordinator.', 'warning')
                    return redirect('/student')
                attempt_id = existing['attempt_id']
            else:
                cursor.execute('INSERT INTO Quiz_Attempts (user_id, quiz_id, total_score, status) VALUES (%s, %s, 0, %s)', (session['user_id'], quiz_id, 'In-Progress'))
                conn.commit()
                attempt_id = cursor.lastrowid

            try:
                cursor.execute('SELECT * FROM Questions WHERE quiz_id=%s ORDER BY module, question_id ASC', (quiz_id,))
            except Exception:
                cursor.execute('SELECT * FROM Questions WHERE quiz_id=%s ORDER BY question_id ASC', (quiz_id,))

            questions_raw = list(cursor.fetchall())

            grouped_qs = {}
            for q in questions_raw:
                mod = q.get('module') or 'General'
                if mod not in grouped_qs:
                    grouped_qs[mod] = []
                grouped_qs[mod].append(q)

            questions_raw = []
            for mod in grouped_qs:
                questions_raw.extend(_stable_shuffle(grouped_qs[mod], f'attempt:{attempt_id}:module:{mod}'))

            questions_processed = []
            for q in questions_raw:
                if q['question_type'] == 'MCQ':
                    options = _stable_shuffle([
                        {'key': 'A', 'text': q['option_a']},
                        {'key': 'B', 'text': q['option_b']},
                        {'key': 'C', 'text': q['option_c']},
                        {'key': 'D', 'text': q['option_d']}
                    ], f'attempt:{attempt_id}:question:{q["question_id"]}:options')
                    q['shuffled_options'] = options
                questions_processed.append(q)

            cursor.execute('SELECT question_id, selected_option FROM Quiz_Responses WHERE attempt_id=%s', (attempt_id,))
            saved = {row['question_id']: {'opt': row['selected_option']} for row in cursor.fetchall()}
    finally:
        conn.close()

    return render_template('exam_console.html', 
                          questions=questions_processed, 
                          attempt_id=attempt_id, 
                          quiz_meta=meta, 
                          saved_responses=saved, 
                          user=user_info)

@quiz_bp.route('/api/save_answer', methods=['POST'])
def save_answer():
    data = request.json
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('''
            INSERT INTO Quiz_Responses (attempt_id, question_id, selected_option) 
            VALUES (%s, %s, %s) 
            ON DUPLICATE KEY UPDATE selected_option=%s
        ''', (data['attempt_id'], data['question_id'], data['option'], data['option']))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

@quiz_bp.route('/api/submit_quiz', methods=['POST'])
def submit_quiz():
    aid = request.json['attempt_id']
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('''
            SELECT SUM(q.marks) as score
            FROM Quiz_Responses r
            JOIN Questions q ON r.question_id=q.question_id
            WHERE r.attempt_id=%s AND r.selected_option=q.correct_option
        ''', (aid,))
        result = cursor.fetchone()
        user_score = int(result['score']) if result and result['score'] else 0

        cursor.execute('''
            SELECT SUM(marks) as total
            FROM Questions
            WHERE quiz_id=(SELECT quiz_id FROM Quiz_Attempts WHERE attempt_id=%s)
        ''', (aid,))
        total_res = cursor.fetchone()
        total_possible = int(total_res['total']) if total_res and total_res['total'] else 100

        percentage = (user_score / total_possible) * 100
        approved = 1 if percentage >= 40 else 0

        cursor.execute('''
            UPDATE Quiz_Attempts
            SET total_score=%s, status=%s, certificate_approved=%s
            WHERE attempt_id=%s
        ''', (user_score, 'Completed', approved, aid))

    conn.commit()
    conn.close()
    return jsonify({'score': user_score})
