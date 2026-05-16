from flask import Blueprint, request, jsonify, session
from utils import get_db_connection, collect_selected_ai_preview_rows

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/get_seats/<int:center_id>')
def get_seats(center_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('SELECT total_rows, total_cols FROM Exam_Centers WHERE center_id=%s', (center_id,))
        center = cursor.fetchone()

        cursor.execute('''
            SELECT user_id, full_name, seat_row, seat_col, goal_type, team_name
            FROM Users WHERE center_id=%s
        ''', (center_id,))
        users = cursor.fetchall()
    conn.close()
    return jsonify({
        'rows': center['total_rows'],
        'cols': center['total_cols'],
        'users': users
    })

@api_bp.route('/get_sessions')
def get_sessions():
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db_connection()
    sessions = []
    if conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT quiz_id, title, batch, year, start_time 
                FROM Quizzes 
                ORDER BY start_time DESC
                LIMIT 50
            ''')
            sessions = cursor.fetchall()
        conn.close()
    return jsonify({'sessions': sessions})

@api_bp.route('/save_questions_to_sessions', methods=['POST'])
def save_questions_to_sessions():
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.json
    preview_token = data.get('preview_token')
    session_ids = data.get('session_ids', [])
    questions_data = data.get('questions', [])
    
    if not session_ids:
        return jsonify({'success': False, 'error': 'No sessions selected'})
    
    if not questions_data:
        return jsonify({'success': False, 'error': 'No questions to save'})
    
    conn = get_db_connection()
    total_inserted = 0
    errors = []
    
    try:
        with conn.cursor() as cursor:
            for session_id in session_ids:
                try:
                    for q in questions_data:
                        cursor.execute('''
                            INSERT INTO Questions 
                            (quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ''', (
                            session_id,
                            q.get('question_text', ''),
                            q.get('option_a', ''),
                            q.get('option_b', ''),
                            q.get('option_c', ''),
                            q.get('option_d', ''),
                            q.get('correct_option', 'A'),
                            q.get('marks', 1)
                        ))
                        total_inserted += 1
                except Exception as e:
                    errors.append(f"Session {session_id}: {str(e)}")
                    continue
            
            conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()
    
    if errors:
        return jsonify({
            'success': True, 
            'partial': True,
            'total_inserted': total_inserted,
            'warnings': errors
        })
    
    return jsonify({
        'success': True,
        'total_inserted': total_inserted,
        'sessions_count': len(session_ids)
    })

@api_bp.route('/get_ai_preview_questions', methods=['POST'])
def get_ai_preview_questions():
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    from utils import get_cached_ai_preview_state
    
    data = request.json
    preview_token = data.get('preview_token')
    
    preview_state, _ = get_cached_ai_preview_state(preview_token)
    if not preview_state:
        return jsonify({'error': 'Preview session expired'}), 400
    
    selected_rows = collect_selected_ai_preview_rows(request.form)
    
    if not selected_rows:
        return jsonify({'error': 'No questions selected'}), 400
    
    return jsonify({'questions': selected_rows})

@api_bp.route('/assign_seat', methods=['POST'])
def assign_seat():
    data = request.json
    identifier = data['student']

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('SELECT user_id FROM Users WHERE email=%s OR user_id=%s', (identifier, identifier))
        user = cursor.fetchone()

        if not user:
            return jsonify({'status': 'error', 'message': 'Student not found'})

        cursor.execute('''
            UPDATE Users SET center_id=%s, seat_row=%s, seat_col=%s
            WHERE user_id=%s
        ''', (data['center_id'], data['seat_row'], data['seat_col'], user['user_id']))

    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

@api_bp.route('/terminate_exam', methods=['POST'])
def terminate_exam():
    if 'user_id' not in session:
        return jsonify({'status': 'error'})

    data = request.json
    attempt_id = data.get('attempt_id')
    reason = data.get('reason', 'Security Violation')

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('''
            UPDATE Quiz_Attempts
            SET status=%s, total_score=0, certificate_approved=0
            WHERE attempt_id=%s
        ''', ('Terminated', attempt_id))

        cursor.execute('UPDATE Users SET is_blocked=1 WHERE user_id=%s', (session['user_id'],))

    conn.commit()
    conn.close()

    session.clear()
    return jsonify({'status': 'terminated'})

@api_bp.route('/stats/dept_analytics')
def dept_analytics():
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'status': 'error'}), 403

    batch = request.args.get('batch')
    year = request.args.get('year')

    conn = get_db_connection()
    data = {'labels': [], 'values': []}

    if conn:
        with conn.cursor() as cursor:
            sql = '''
                SELECT u.department, AVG((qa.total_score / COALESCE(NULLIF(q.total_marks, 0), 100)) * 100) as avg_pct
                FROM Quiz_Attempts qa
                JOIN Users u ON qa.user_id = u.user_id
                JOIN Quizzes q ON qa.quiz_id = q.quiz_id
                WHERE u.role = %s
            '''
            params = ['Student']
            if batch:
                sql += ' AND u.enrolled_session = %s'
                params.append(batch)
            if year:
                sql += ' AND u.study_year = %s'
                params.append(year)
            sql += ' GROUP BY u.department'

            cursor.execute(sql, tuple(params))
            for r in cursor.fetchall():
                if r['department']:
                    data['labels'].append(r['department'])
                    data['values'].append(round(float(r['avg_pct']), 2))
        conn.close()
    return jsonify(data)