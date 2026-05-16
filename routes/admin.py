from flask import Blueprint, request, redirect, render_template, jsonify, flash, session, Response, current_app
from utils import get_db_connection
import csv
import io

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
                       q.title, a.certificate_approved
                FROM Quiz_Attempts a
                JOIN Users u ON a.user_id=u.user_id
                JOIN Quizzes q ON a.quiz_id=q.quiz_id
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
        cursor.execute('DELETE FROM Quizzes WHERE quiz_id=%s', (quiz_id,))
    conn.commit()
    conn.close()
    flash('Session deleted successfully!', 'success')
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

@admin_bp.route('/results')
@require_admin_or_coordinator
def manage_results():
    conn = get_db_connection()
    attempts = []
    if conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT a.*, u.full_name, u.email, u.roll_number, u.department, u.study_year,
                       u.enrolled_session, q.title, q.batch
                FROM Quiz_Attempts a
                JOIN Users u ON a.user_id = u.user_id
                JOIN Quizzes q ON a.quiz_id = q.quiz_id
                ORDER BY a.attempt_id DESC
            ''')
            attempts = cursor.fetchall()
        conn.close()
    return render_template('admin_results.html', attempts=attempts)

@admin_bp.route('/export_results')
@require_admin_or_coordinator
def export_results():
    conn = get_db_connection()
    attempts = []
    if conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT a.*, u.full_name, u.email, u.roll_number, u.department, u.study_year,
                       u.enrolled_session, q.title, q.batch
                FROM Quiz_Attempts a
                JOIN Users u ON a.user_id = u.user_id
                JOIN Quizzes q ON a.quiz_id = q.quiz_id
                ORDER BY a.attempt_id DESC
            ''')
            attempts = cursor.fetchall()
        conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Name', 'Email', 'Roll No', 'Department', 'Year', 'Session', 'Quiz', 'Batch', 'Score', 'Status', 'Time'])
    for a in attempts:
        writer.writerow([
            a.get('full_name'), a.get('email'), a.get('roll_number'),
            a.get('department'), a.get('study_year'), a.get('enrolled_session'),
            a.get('title'), a.get('batch'), a.get('total_score'),
            a.get('status'), a.get('submitted_at')
        ])
    return Response(output.getvalue(), mimetype='text/csv', headers={'Content-disposition': 'attachment; filename=results.csv'})

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

@admin_bp.route('/edit_student/<int:user_id>')
@require_admin
def edit_student_page(user_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('SELECT * FROM Users WHERE user_id=%s', (user_id,))
        user = cursor.fetchone()
        cursor.execute('SELECT batch_name as batch FROM Batches ORDER BY batch_name')
        sessions = cursor.fetchall()
        cursor.execute('SELECT center_id, center_name, capacity FROM Exam_Centers')
        centers = cursor.fetchall()
    conn.close()
    return render_template('edit_student.html', user=user, sessions=sessions, centers=centers)

@admin_bp.route('/update_student', methods=['POST'])
@require_admin
def update_student():
    user_id = request.form.get('user_id')
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    enrolled_session = request.form.get('enrolled_session')
    new_center_id = request.form.get('allotted_center_id')
    att_p = request.form.get('attendance_present', 0)
    att_t = request.form.get('attendance_total', 0)
    if new_center_id == '':
        new_center_id = None

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('UPDATE Users SET full_name=%s, email=%s, enrolled_session=%s, allotted_center_id=%s, attendance_present=%s, attendance_total=%s WHERE user_id=%s',
                       (full_name, email, enrolled_session, new_center_id, att_p, att_t, user_id))
    conn.commit()
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
