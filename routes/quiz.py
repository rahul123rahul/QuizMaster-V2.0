from flask import Blueprint, request, redirect, render_template, jsonify, flash, session, send_file
from utils import get_db_connection
from datetime import datetime, timedelta
from certificate_generator import generate_certificate_pdf
import random
import json

quiz_bp = Blueprint('quiz', __name__, template_folder='../templates')

def _stable_shuffle(items, seed_value):
    shuffled = list(items)
    rng = random.Random(str(seed_value))
    rng.shuffle(shuffled)
    return shuffled

def _normalize_quiz_question(q, attempt_id=None):
    raw_type = (q.get('question_type') or '').strip().lower()
    clean_type = raw_type.replace(' ', '_').replace('-', '_')
    meta = {}
    if q.get('metadata_json'):
        try:
            meta = json.loads(q['metadata_json']) if isinstance(q['metadata_json'], str) else q['metadata_json']
        except Exception:
            meta = {}

    meta_type = str(meta.get('question_type') or meta.get('type') or meta.get('selection_type') or '').strip().lower().replace(' ', '_').replace('-', '_')
    combined_type = f"{clean_type} {meta_type}".strip()

    # 1. Determine if this question is a Coding Challenge
    coding_types = {'code', 'coding', 'programming'}
    is_coding = False
    if clean_type in coding_types or meta_type in coding_types:
        is_coding = True
    elif (q.get('test_input') or q.get('test_output')) and not any(k in combined_type for k in ['blank', 'fill', 'fib', 'single', 'multi', 'select', 'dropdown', 'true', 'false', 'boolean', 'tf', 'mscq']):
        is_coding = True
    elif (q.get('module') or '').strip().lower() == 'coding' and not q.get('option_a') and not meta.get('options') and not any(k in combined_type for k in ['blank', 'fill', 'fib', 'single', 'multi', 'select', 'dropdown', 'true', 'false', 'boolean', 'tf']):
        is_coding = True

    # 1b. Check Image MCQ metadata
    image_url = meta.get('image_url') or q.get('image_url') or ''
    image_pos = str(meta.get('image_position') or 'above').lower().strip()
    if image_pos not in ['above', 'below', 'beside']:
        image_pos = 'above'
    image_cat = meta.get('image_category') or 'Diagram'
    is_image_mcq = (clean_type in {'image_mcq', 'image', 'image_based'}) or bool(image_url)

    # 2. Determine normalized Question Type (Coding + 5 Quiz Question Types)
    if is_coding:
        norm_type = 'coding'
    elif any(k in combined_type for k in ['blank', 'fill', 'fib']):
        norm_type = 'fill_blank'
    elif any(k in combined_type for k in ['true_false', 'truefalse', 'boolean', 'tf', 'true', 'false']):
        norm_type = 'true_false'
    elif any(k in combined_type for k in ['mscq_multiple', 'multiple', 'multi', 'checkbox']) or (is_image_mcq and meta.get('selectionType') == 'multiple'):
        norm_type = 'mscq_multiple'
    elif any(k in combined_type for k in ['mscq_select', 'dropdown', 'select', 'select_dropdown']):
        norm_type = 'mscq_select'
    else:
        norm_type = 'mscq_single'

    # 3. Extract and configure Options
    options = []
    if norm_type == 'fill_blank':
        options = []
    elif norm_type == 'true_false':
        options = [
            {'key': 'True', 'text': 'True'},
            {'key': 'False', 'text': 'False'}
        ]
    elif meta.get('options') and isinstance(meta['options'], list) and len(meta['options']) > 0:
        for opt in meta['options']:
            if isinstance(opt, dict):
                k = str(opt.get('id') or opt.get('key') or '').strip()
                t = str(opt.get('text') or opt.get('value') or '').strip()
                if t:
                    options.append({'key': k or chr(65 + len(options)), 'text': t})
            elif opt and str(opt).strip():
                options.append({'key': chr(65 + len(options)), 'text': str(opt).strip()})

    # Fallback to option_a, option_b, option_c, option_d columns if meta.options was empty or had no text
    if not options and norm_type not in {'fill_blank', 'true_false', 'coding'}:
        for key, field in [('A', 'option_a'), ('B', 'option_b'), ('C', 'option_c'), ('D', 'option_d')]:
            val = q.get(field)
            if val is not None and str(val).strip() != '':
                options.append({'key': key, 'text': str(val).strip()})

    q['is_coding'] = is_coding
    q['is_image_mcq'] = is_image_mcq
    q['image_url'] = image_url
    q['image_position'] = image_pos
    q['image_category'] = image_cat
    q['question_type_norm'] = norm_type
    q['meta_data'] = meta

    # Shuffling options for single choice if desired, else keep stable
    if norm_type in {'mscq_single'} and attempt_id and len(options) > 1:
        q['shuffled_options'] = _stable_shuffle(options, f'attempt:{attempt_id}:question:{q["question_id"]}:options')
    else:
        q['shuffled_options'] = options

    # 4. Fill in the Blank specifics
    if norm_type == 'fill_blank':
        acc = meta.get('acceptedAnswers') or []
        if not acc and q.get('correct_option'):
            acc = [str(q['correct_option']).strip()]
        q['accepted_answers'] = acc
        q['case_sensitive'] = bool(meta.get('caseSensitive', False))

    return q

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
                    SELECT u.*, 
                           COALESCE(c.center_name, c2.center_name) AS center_name,
                           COALESCE(c.address, c2.address) AS address,
                           COALESCE(c.city, c2.city) AS city 
                    FROM Users u 
                    LEFT JOIN Exam_Centers c ON u.center_id = c.center_id 
                    LEFT JOIN Exam_Centers c2 ON u.allotted_center_id = c2.center_id 
                    WHERE u.user_id=%s
                ''', (session['user_id'],))
                user_info = cursor.fetchone()

                if user_info and not user_info.get('center_name'):
                    cursor.execute('SELECT center_name, address, city FROM Exam_Centers ORDER BY center_id ASC LIMIT 1')
                    fallback_center = cursor.fetchone()
                    if fallback_center:
                        user_info['center_name'] = fallback_center.get('center_name')
                        user_info['address'] = fallback_center.get('address')
                        user_info['city'] = fallback_center.get('city')

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
                    SELECT 
                        COALESCE(q.title, a.quiz_title, 'Completed Assessment') AS title,
                        COALESCE(q.total_marks, a.total_marks, 100) AS total_marks,
                        a.total_score, a.status, a.attempt_id, a.certificate_approved,
                        a.end_time, a.submitted_at
                    FROM Quiz_Attempts a 
                    LEFT JOIN Quizzes q ON a.quiz_id=q.quiz_id 
                    WHERE a.user_id=%s 
                    ORDER BY a.attempt_id DESC
                ''', (session['user_id'],))
                history = cursor.fetchall()

                cursor.execute('SELECT * FROM Announcements WHERE id=1')
                ann = cursor.fetchone()
                msg = ann['message'] if (ann and ann['is_active']) else None
        finally:
            conn.close()

    if not user_info:
        user_info = {
            'full_name': session.get('name', 'Student'),
            'email': session.get('email', ''),
            'roll_number': session.get('roll_number', ''),
            'department': session.get('department', ''),
            'study_year': session.get('study_year', ''),
            'section': session.get('section', ''),
            'attendance_present': 0,
            'attendance_total': 0,
            'avatar': None
        }

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
                    SELECT COALESCE(q.title, a.quiz_title, 'Completed Assessment') AS title,
                           a.attempt_id, a.total_score, a.status, a.start_time, a.end_time, a.certificate_approved,
                           COALESCE((SELECT COUNT(*) FROM Questions WHERE quiz_id=a.quiz_id), a.total_questions, 0) as total_questions,
                           (SELECT COUNT(*) FROM Quiz_Responses WHERE attempt_id=a.attempt_id AND selected_option IS NOT NULL) as answered
                    FROM Quiz_Attempts a 
                    LEFT JOIN Quizzes q ON a.quiz_id=q.quiz_id 
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
                       COALESCE(q.title, a.quiz_title, 'Completed Assessment') AS title, u.full_name
                FROM Quiz_Attempts a
                LEFT JOIN Quizzes q ON a.quiz_id = q.quiz_id
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
                       COALESCE(q.title, a.quiz_title, 'Completed Assessment') AS title, u.full_name
                FROM Quiz_Attempts a
                LEFT JOIN Quizzes q ON a.quiz_id = q.quiz_id
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
                       COALESCE(q.title, a.quiz_title, 'Completed Assessment') AS title, u.full_name
                FROM Quiz_Attempts a
                LEFT JOIN Quizzes q ON a.quiz_id = q.quiz_id
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
                cursor.execute('''
                    INSERT INTO Quiz_Attempts (user_id, quiz_id, quiz_title, total_marks, batch, total_questions, total_score, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 0, %s)
                ''', (
                    session['user_id'],
                    quiz_id,
                    meta.get('title'),
                    meta.get('total_marks') or 100.0,
                    meta.get('batch'),
                    meta.get('total_questions') or 0,
                    'In-Progress'
                ))
                conn.commit()
                attempt_id = cursor.lastrowid

            cursor.execute('SELECT * FROM Questions WHERE quiz_id=%s ORDER BY question_id ASC', (quiz_id,))
            questions_raw = list(cursor.fetchall())

            MODULE_SORT_ORDER = {
                'Single Choice': 1,
                'Multiple Choice': 2,
                'Select Dropdown': 3,
                'Fill in the Blanks': 4,
                'True / False': 5,
                'Coding': 6,
                'Coding Challenge': 6
            }

            def _derive_mod(q_obj, norm_type):
                m = (q_obj.get('module') or '').strip()
                if m and m.lower() not in ['general', 'default', 'none', '']:
                    return m
                if norm_type == 'mscq_single': return 'Single Choice'
                elif norm_type == 'mscq_multiple': return 'Multiple Choice'
                elif norm_type == 'mscq_select': return 'Select Dropdown'
                elif norm_type == 'fill_blank': return 'Fill in the Blanks'
                elif norm_type == 'true_false': return 'True / False'
                elif norm_type == 'coding': return 'Coding'
                return 'Single Choice'

            # 1. Normalize all questions first
            normalized_list = []
            for q in questions_raw:
                q_norm = _normalize_quiz_question(dict(q), attempt_id=attempt_id)
                mod_name = _derive_mod(q_norm, q_norm.get('question_type_norm'))
                q_norm['module'] = mod_name
                normalized_list.append(q_norm)

            # 2. Group by module
            grouped_qs = {}
            for q in normalized_list:
                mod = q['module']
                if mod not in grouped_qs:
                    grouped_qs[mod] = []
                grouped_qs[mod].append(q)

            # 3. Sort modules according to standard 5-question-type + Coding sequence
            sorted_module_names = sorted(
                grouped_qs.keys(),
                key=lambda m: (MODULE_SORT_ORDER.get(m, 99), m)
            )

            questions_processed = []
            modules_summary = {}
            for mod in sorted_module_names:
                mod_qs = grouped_qs[mod]
                start_idx = len(questions_processed)
                questions_processed.extend(mod_qs)
                modules_summary[mod] = {
                    'count': len(mod_qs),
                    'first_idx': start_idx,
                    'question_ids': [q['question_id'] for q in mod_qs]
                }

            cursor.execute('SELECT question_id, selected_option FROM Quiz_Responses WHERE attempt_id=%s', (attempt_id,))
            saved = {row['question_id']: {'opt': row['selected_option']} for row in cursor.fetchall()}
    finally:
        conn.close()

    return render_template('exam_console.html', 
                          questions=questions_processed, 
                          attempt_id=attempt_id, 
                          quiz_meta=meta, 
                          modules_summary=modules_summary,
                          saved_responses=saved, 
                          user=user_info)

@quiz_bp.route('/api/save_answer', methods=['POST'])
def save_answer():
    data = request.json
    conn = get_db_connection()
    with conn.cursor() as cursor:
        opt = data.get('option')
        is_att = 1 if (opt is not None and str(opt).strip() != '') else 0
        cursor.execute('''
            INSERT INTO Quiz_Responses (attempt_id, question_id, selected_option, is_attempted) 
            VALUES (%s, %s, %s, %s) 
            ON DUPLICATE KEY UPDATE selected_option=%s, is_attempted=%s
        ''', (data['attempt_id'], data['question_id'], opt, is_att, opt, is_att))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

@quiz_bp.route('/api/submit_quiz', methods=['POST'])
def submit_quiz():
    aid = request.json.get('attempt_id')
    if not aid:
        return jsonify({'error': 'attempt_id is required'}), 400

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('SELECT quiz_id FROM Quiz_Attempts WHERE attempt_id=%s', (aid,))
        attempt_row = cursor.fetchone()
        if not attempt_row:
            conn.close()
            return jsonify({'error': 'Attempt not found'}), 404
        quiz_id = attempt_row['quiz_id']

        cursor.execute('SELECT * FROM Questions WHERE quiz_id=%s', (quiz_id,))
        questions = cursor.fetchall()

        cursor.execute('SELECT question_id, selected_option, is_attempted FROM Quiz_Responses WHERE attempt_id=%s', (aid,))
        responses = {r['question_id']: r for r in cursor.fetchall()}

        user_score = 0.0
        total_possible = 0.0

        for q in questions:
            marks = float(q.get('marks') or 1)
            total_possible += marks
            neg_marks = float(q.get('negative_marks') or 0)
            
            resp = responses.get(q['question_id'])
            if not resp or not resp.get('is_attempted'):
                continue
            
            user_ans = (resp.get('selected_option') or '').strip()
            if not user_ans:
                continue

            q_norm = _normalize_quiz_question(dict(q))
            q_type = q_norm['question_type_norm']
            meta = q_norm['meta_data']
            correct_opt = (q.get('correct_option') or meta.get('correctAnswer') or '').strip()

            is_correct = False

            if q_norm['is_coding']:
                if user_ans.lower() in {'accepted', 'pass'} or 'pass' in user_ans.lower():
                    is_correct = True
                else:
                    try:
                        from utils import split_test_case_block, normalize_judge_output
                        from code_runner import execute_code
                        raw_inputs = split_test_case_block(q.get('test_input'))
                        raw_outputs = split_test_case_block(q.get('test_output'))
                        if raw_outputs:
                            exec_res = execute_code(user_ans, 'python', stdin_data=(raw_inputs[0] if raw_inputs else ''))
                            actual = (exec_res.get('stdout') or '').strip()
                            if normalize_judge_output(actual) == normalize_judge_output(raw_outputs[0]):
                                is_correct = True
                        elif user_ans:
                            is_correct = True
                    except Exception:
                        if user_ans:
                            is_correct = True

            elif q_type == 'mscq_single':
                is_correct = (user_ans.upper() == correct_opt.upper())

            elif q_type == 'mscq_multiple':
                u_set = {x.strip().upper() for x in user_ans.split(',') if x.strip()}
                c_set = {x.strip().upper() for x in correct_opt.split(',') if x.strip()}
                is_correct = (u_set == c_set and len(u_set) > 0)

            elif q_type == 'mscq_select':
                is_correct = (user_ans.upper() == correct_opt.upper())

            elif q_type == 'fill_blank':
                accepted = meta.get('acceptedAnswers') or []
                if not accepted and correct_opt:
                    accepted = [correct_opt]
                case_sensitive = meta.get('caseSensitive', True)
                if case_sensitive:
                    is_correct = any(user_ans == str(acc).strip() for acc in accepted)
                else:
                    is_correct = any(user_ans.lower() == str(acc).strip().lower() for acc in accepted)

            elif q_type == 'true_false':
                norm_user = 'true' if user_ans.lower() in {'true', 't', 'a', 'yes', '1'} else 'false'
                norm_corr = 'true' if correct_opt.lower() in {'true', 't', 'a', 'yes', '1'} else 'false'
                is_correct = (norm_user == norm_corr)

            if is_correct:
                user_score += marks
            else:
                if neg_marks > 0:
                    user_score -= neg_marks

        user_score = max(0.0, round(user_score, 2))
        total_possible = max(1.0, round(total_possible, 2))
        percentage = (user_score / total_possible) * 100
        approved = 1 if percentage >= 40 else 0

        score_display = int(user_score) if user_score.is_integer() else user_score

        cursor.execute('''
            UPDATE Quiz_Attempts
            SET total_score=%s, total_marks=%s, status=%s, certificate_approved=%s, end_time=NOW(), submitted_at=NOW()
            WHERE attempt_id=%s
        ''', (score_display, total_possible, 'Completed', approved, aid))

    conn.commit()
    conn.close()
    return jsonify({'score': score_display, 'total': total_possible, 'percentage': round(percentage, 1)})
