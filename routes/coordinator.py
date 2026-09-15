from flask import Blueprint, request, redirect, render_template, jsonify, flash, session
from utils import get_db_connection

coordinator_bp = Blueprint('coordinator', __name__, template_folder='../templates', url_prefix='/coordinator')

def require_coordinator(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'Coordinator':
            return redirect('/')
        return f(*args, **kwargs)
    return decorated

@coordinator_bp.route('/')
@require_coordinator
def dashboard():
    quizzes = []
    questions = []
    students = []
    batches = []
    name = session.get('name', 'Coordinator')

    conn = get_db_connection()

    if conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM Quizzes ORDER BY quiz_id DESC')
            quizzes = cursor.fetchall()

            cursor.execute('SELECT * FROM Questions ORDER BY question_id DESC')
            questions = cursor.fetchall()

            cursor.execute('SELECT * FROM Users WHERE role=%s', ('Student',))
            students = cursor.fetchall()

            try:
                cursor.execute('SELECT batch_name as batch FROM Batches ORDER BY batch_name DESC')
                batches = cursor.fetchall()
            except Exception:
                batches = []

        conn.close()

    return render_template('coordinator_dashboard.html',
                          quizzes=quizzes, questions=questions,
                          students=students, batches=batches, name=name)

@coordinator_bp.route('/students')
@require_coordinator
def manage_students():
    from utils import build_student_query
    query, params = build_student_query(request.args)
    conn = get_db_connection()
    students, batches, departments = [], [], []
    if conn:
        with conn.cursor() as cursor:
            cursor.execute(query, tuple(params))
            students = cursor.fetchall()
            
            # Fetch all registered batches from Batches table (created at Create Batches)
            batch_set = set()
            try:
                cursor.execute("SELECT batch_name FROM Batches WHERE batch_name IS NOT NULL AND batch_name != '' ORDER BY batch_name DESC")
                for r in cursor.fetchall():
                    b = (r.get('batch_name') or '').strip()
                    if b: batch_set.add(b)
            except Exception:
                pass
            try:
                cursor.execute("SELECT DISTINCT batch FROM Quizzes WHERE batch IS NOT NULL AND batch != ''")
                for r in cursor.fetchall():
                    b = (r.get('batch') or '').strip()
                    if b: batch_set.add(b)
            except Exception:
                pass
            try:
                cursor.execute("SELECT DISTINCT enrolled_session FROM Users WHERE enrolled_session IS NOT NULL AND enrolled_session != ''")
                for r in cursor.fetchall():
                    b = (r.get('enrolled_session') or '').strip()
                    if b: batch_set.add(b)
            except Exception:
                pass
            try:
                cursor.execute("SELECT DISTINCT selected_session FROM Users WHERE selected_session IS NOT NULL AND selected_session != ''")
                for r in cursor.fetchall():
                    b = (r.get('selected_session') or '').strip()
                    if b: batch_set.add(b)
            except Exception:
                pass
            batches = [{'batch': b} for b in sorted(batch_set, reverse=True)]

            cursor.execute('SELECT DISTINCT department FROM Users WHERE role=%s AND department IS NOT NULL AND department != %s', ('Student', ''))
            departments = cursor.fetchall()
        conn.close()
    return render_template('manage_students.html', students=students, batches=batches, departments=departments)

@coordinator_bp.route('/sessions')
@require_coordinator
def manage_sessions():
    conn = get_db_connection()
    quizzes = []
    batches = []
    if conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM Quizzes ORDER BY start_time DESC')
            quizzes = cursor.fetchall()
            cursor.execute('SELECT batch_name as batch FROM Batches ORDER BY batch_name DESC')
            batches = cursor.fetchall()
        conn.close()
    return render_template('manage_sessions.html', quizzes=quizzes, batches=batches)