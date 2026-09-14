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

@api_bp.route('/run_code', methods=['POST'])
def run_code():
    data = request.json or {}
    attempt_id = data.get('attempt_id')
    question_id = data.get('question_id')
    code = data.get('code', '')
    language = data.get('language', 'python')
    mode = data.get('mode', 'official')
    custom_stdin = data.get('stdin', '')

    from code_runner import execute_code
    from utils import split_test_case_block, normalize_judge_output

    if not code.strip():
        return jsonify({'status': 'error', 'output': 'No code provided to execute.'}), 400

    # 1. Custom Stdin Mode
    if mode == 'custom':
        exec_res = execute_code(code, language, stdin_data=custom_stdin)
        if exec_res.get('stderr') and not exec_res.get('stdout'):
            return jsonify({'status': 'error', 'output': exec_res.get('stderr')})
        out = exec_res.get('stdout') or ''
        if exec_res.get('stderr'):
            out += f"\n[Errors / Warnings]:\n{exec_res.get('stderr')}"
        return jsonify({'status': 'success', 'output': out.strip() or 'No Output'})

    # 2. Official Test Cases Mode
    conn = get_db_connection()
    q_data = None
    if conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT question_id, test_input, test_output, marks FROM Questions WHERE question_id=%s", (question_id,))
            q_data = cursor.fetchone()
        conn.close()

    if not q_data:
        exec_res = execute_code(code, language, stdin_data="")
        out = exec_res.get('stdout') or exec_res.get('stderr') or 'No Output'
        return jsonify({
            'status': 'success',
            'verdict': exec_res.get('verdict', 'Accepted'),
            'results': [{
                'case_num': 1,
                'status': 'Pass' if exec_res.get('verdict') == 'Accepted' else 'Error',
                'input': 'None',
                'expected': 'Execution Success',
                'actual': out.strip()
            }],
            'output': out.strip()
        })

    raw_inputs = split_test_case_block(q_data.get('test_input'))
    raw_outputs = split_test_case_block(q_data.get('test_output'))

    if not raw_inputs and not raw_outputs:
        raw_inputs = [""]
        raw_outputs = [""]
    elif not raw_inputs:
        raw_inputs = [""] * len(raw_outputs)
    elif not raw_outputs:
        raw_outputs = [""] * len(raw_inputs)

    case_count = max(len(raw_inputs), len(raw_outputs))
    results = []
    passed_count = 0
    first_error = None

    for idx in range(case_count):
        inp = raw_inputs[idx] if idx < len(raw_inputs) else ""
        exp = raw_outputs[idx] if idx < len(raw_outputs) else ""

        run_res = execute_code(code, language, stdin_data=inp)
        actual = (run_res.get('stdout') or '').strip()
        err = (run_res.get('stderr') or '').strip()
        verdict = run_res.get('verdict', 'Accepted')

        if verdict == 'Time Limit Exceeded':
            case_status = 'Error'
            actual_display = f"Time Limit Exceeded (3.0s)\n{err}".strip()
            if not first_error:
                first_error = 'Time Limit Exceeded'
        elif err and not actual:
            case_status = 'Error'
            actual_display = err
            if not first_error:
                first_error = 'Runtime Error' if verdict != 'Compilation Error' else 'Compilation Error'
        else:
            norm_actual = normalize_judge_output(actual)
            norm_exp = normalize_judge_output(exp)

            if norm_actual == norm_exp:
                case_status = 'Pass'
                passed_count += 1
                actual_display = actual
            else:
                case_status = 'Fail'
                actual_display = actual if actual else (err or 'No Output')

        results.append({
            'case_num': idx + 1,
            'status': case_status,
            'input': inp if inp else 'No Input',
            'expected': exp if exp else 'No expected output configured',
            'actual': actual_display
        })

    total_cases = len(results)
    if passed_count == total_cases and total_cases > 0:
        final_verdict = 'Accepted'
    elif first_error:
        final_verdict = first_error
    else:
        final_verdict = 'Wrong Answer'

    # Save code to Quiz_Responses
    if attempt_id and question_id:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO Quiz_Responses (attempt_id, question_id, selected_option, is_attempted)
                    VALUES (%s, %s, %s, 1)
                    ON DUPLICATE KEY UPDATE selected_option=VALUES(selected_option), is_attempted=1
                ''', (attempt_id, question_id, code))
            conn.close()

    return jsonify({
        'status': 'success',
        'verdict': final_verdict,
        'passed_count': passed_count,
        'total_cases': total_cases,
        'results': results
    })