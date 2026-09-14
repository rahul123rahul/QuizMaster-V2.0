import sys, os
sys.path.insert(0, os.path.abspath('.'))
from main import app
from utils import get_db_connection
from routes.quiz import _normalize_quiz_question
from flask import render_template

with app.test_request_context():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM Questions WHERE quiz_id = 8 ORDER BY question_id ASC')
    raw = cursor.fetchall()
    conn.close()
    
    proc = [_normalize_quiz_question(dict(q), attempt_id=1) for q in raw]
    html = render_template('exam_console.html', questions=proc, attempt_id=1, quiz_meta={'duration_minutes': 60, 'title': 'Test Quiz'}, saved_responses={}, user={'full_name': 'Test User'})
    
    print('Rendered HTML length:', len(html))
    for i, q in enumerate(proc):
        qid = q['question_id']
        has_radio = f'opt-group-{qid}' in html and f'selectSingleOpt(this, \'{qid}\'' in html
        has_multi = f'opt-group-{qid}' in html and f'toggleMultiOpt(this, \'{qid}\'' in html
        has_select = f'dropdown-{qid}' in html and f'selectDropdownOpt(\'{qid}\'' in html
        has_blank = f'blank-input-{qid}' in html and f'handleBlankInput(\'{qid}\'' in html
        has_tf = f'opt-group-{qid}' in html and f'selectTrueFalseOpt(this, \'{qid}\'' in html
        
        assigned = []
        if has_radio: assigned.append("Radio (Single)")
        if has_multi: assigned.append("Checkbox (Multi)")
        if has_select: assigned.append("Dropdown (Select)")
        if has_blank: assigned.append("Fill in the Blank")
        if has_tf: assigned.append("True/False")
        
        print(f"Q{i+1:02d} ID:{qid} Type:{q['question_type_norm']:<15} Module:{q.get('module')} -> Rendered: {assigned}")
