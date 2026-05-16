from flask import Flask, request, redirect, session, render_template, jsonify, flash, send_file, Response, current_app, url_for
from datetime import timedelta, datetime
import os
import sys
import random
import csv
import io
import base64
import time
import threading
import json
import re
from dotenv import load_dotenv
from database import get_db_connection
from certificate_generator import generate_certificate_pdf
from utils import *

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-change-me')

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# Blueprint Registration
from routes.auth import auth_bp
from routes.home import home_bp
from routes.admin import admin_bp
from routes.coordinator import coordinator_bp
from routes.quiz import quiz_bp
from routes.study_materials import study_bp
from routes.api import api_bp

app.register_blueprint(auth_bp)
app.register_blueprint(home_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(coordinator_bp)
app.register_blueprint(quiz_bp)
app.register_blueprint(study_bp)
app.register_blueprint(api_bp)

@app.route('/admin/save_ai_questions', methods=['POST'])
def save_ai_questions():
    from flask import request, redirect, flash
    from utils import collect_selected_ai_preview_rows, get_cached_ai_preview_state
    from database import get_db_connection
    
    preview_token = request.form.get('preview_token')
    quiz_id = request.form.get('quiz_id')
    
    if not quiz_id:
        quiz_id = request.form.get('session_title_select')
    
    preview_state, _ = get_cached_ai_preview_state(preview_token)
    if not preview_state:
        flash('Preview session expired', 'error')
        return redirect('/admin/ai_generate')
    
    selected_rows = collect_selected_ai_preview_rows(request.form)
    
    if not selected_rows:
        flash('No questions selected', 'warning')
        return redirect(f'/admin/ai_preview?preview_token={preview_token}')
    
    if not quiz_id:
        flash('No quiz selected', 'error')
        return redirect('/admin/ai_generate')
    
    conn = get_db_connection()
    added_count = 0
    try:
        with conn.cursor() as cursor:
            for row in selected_rows:
                cursor.execute('''
                    INSERT INTO Questions (quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''', (quiz_id, row['question_text'], row['option_a'], row['option_b'], row['option_c'], row['option_d'], row['correct_option'], row['marks']))
                added_count += 1
        conn.commit()
    except Exception as e:
        flash(f'Error saving questions: {str(e)}', 'error')
        return redirect(f'/admin/ai_preview?preview_token={preview_token}')
    finally:
        conn.close()
    
    flash(f'Successfully added {added_count} questions!', 'success')
    return redirect(f'/admin/edit_session/{quiz_id}')

@app.route('/export_ai_preview_docx', methods=['POST'])
def export_ai_preview_docx():
    from flask import request, Response
    from utils import collect_selected_ai_preview_rows, get_cached_ai_preview_state
    from database import get_db_connection
    import io
    from docx import Document
    
    preview_token = request.form.get('preview_token')
    quiz_id = request.form.get('quiz_id') or request.form.get('session_title_select')
    
    preview_state, _ = get_cached_ai_preview_state(preview_token)
    if not preview_state:
        flash('Preview session expired', 'error')
        return redirect('/admin/ai_generate')
    
    selected_rows = collect_selected_ai_preview_rows(request.form)
    
    doc = Document()
    doc.add_heading('AI Generated Questions', 0)
    
    if quiz_id:
        doc.add_paragraph(f'Quiz ID: {quiz_id}')
    if preview_state.get('generation_prompt'):
        doc.add_paragraph(f'Topic: {preview_state["generation_prompt"]}')
    
    for i, row in enumerate(selected_rows, 1):
        doc.add_paragraph(f'{i}. {row["question_text"]}', style='List Number')
        doc.add_paragraph(f'   A) {row["option_a"]}')
        doc.add_paragraph(f'   B) {row["option_b"]}')
        doc.add_paragraph(f'   C) {row["option_c"]}')
        doc.add_paragraph(f'   D) {row["option_d"]}')
        doc.add_paragraph(f'   Answer: {row["correct_option"]} ({row["marks"]} mark(s))')
        doc.add_paragraph('')
    
    f = io.BytesIO()
    doc.save(f)
    f.seek(0)
    
    return Response(
        f.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-disposition': 'attachment; filename=ai_questions.docx'}
    )

# Coordinator dashboard - using blueprint route instead

@app.route('/question/edit/<int:question_id>', methods=['GET', 'POST'])
def edit_question(question_id):
    conn = get_db_connection()
    question = None
    quizzes = []
    
    if conn:
        with conn.cursor() as cursor:
            if request.method == 'POST':
                question_text = request.form.get('question_text')
                option_a = request.form.get('option_a')
                option_b = request.form.get('option_b')
                option_c = request.form.get('option_c')
                option_d = request.form.get('option_d')
                correct_option = request.form.get('correct_option')
                marks = request.form.get('marks', 1)
                module = request.form.get('module', 'General')
                new_quiz_id = request.form.get('quiz_id')
                
                cursor.execute('''
                    UPDATE Questions 
                    SET quiz_id=%s, question_text=%s, option_a=%s, option_b=%s, option_c=%s, 
                        option_d=%s, correct_option=%s, marks=%s, module=%s
                    WHERE question_id=%s
                ''', (new_quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks, module, question_id))
                conn.commit()
                conn.close()
                return redirect(f'/admin/edit_session/{new_quiz_id}')
            
            cursor.execute('SELECT * FROM Questions WHERE question_id=%s', (question_id,))
            question = cursor.fetchone()
            cursor.execute('SELECT quiz_id, title FROM Quizzes ORDER BY title')
            quizzes = cursor.fetchall()
        conn.close()
    
    if not question:
        return "Question not found", 404
    
    return render_template('edit_question.html', q=question, quizzes=quizzes)

@app.route('/session/edit/<int:quiz_id>', methods=['GET', 'POST'])
def alias_edit_session(quiz_id):
    # A 307 Temporary Redirect is used here to ensure that if this is a POST request, 
    # the form payload and the POST method are preserved when forwarding to the correct route.
    return redirect(f'/admin/edit_session/{quiz_id}', code=307)

@app.route('/question/delete/<int:question_id>')
def delete_question(question_id):
    conn = get_db_connection()
    if conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT quiz_id FROM Questions WHERE question_id=%s', (question_id,))
            result = cursor.fetchone()
            quiz_id = result['quiz_id'] if result else None
            cursor.execute('DELETE FROM Questions WHERE question_id=%s', (question_id,))
            conn.commit()
        conn.close()
        
        if quiz_id:
            return redirect(f'/admin/edit_session/{quiz_id}')
    
    return redirect('/admin/sessions')

@app.route('/upload_docx', methods=['POST'])
def upload_docx():
    from flask import request, jsonify
    from docx import Document
    
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'})
    
    quiz_id = request.form.get('quiz_id')
    if not quiz_id:
        return jsonify({'success': False, 'error': 'No quiz/session selected'})
    
    module_name = request.form.get('module_name', 'General')
    
    try:
        doc = Document(file)
        questions_added = 0
        
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Try to parse as table first (columns: Question, Option A, Option B, Option C, Option D, Correct, Marks)
            tables = doc.tables
            
            if tables:
                # Use first table - skip header row
                table = tables[0]
                for i, row in enumerate(table.rows):
                    if i == 0:  # Skip header
                        continue
                    
                    cells = row.cells
                    if len(cells) >= 2 and cells[0].text.strip():
                        question_text = cells[0].text.strip()
                        option_a = cells[1].text.strip() if len(cells) > 1 else ''
                        option_b = cells[2].text.strip() if len(cells) > 2 else ''
                        option_c = cells[3].text.strip() if len(cells) > 3 else ''
                        option_d = cells[4].text.strip() if len(cells) > 4 else ''
                        correct = cells[5].text.strip().upper() if len(cells) > 5 else 'A'
                        marks = int(cells[6].text.strip()) if len(cells) > 6 else 1
                        
                        # Validate correct option
                        if correct not in ['A', 'B', 'C', 'D']:
                            correct = 'A'
                        
                        if question_text:
                            cursor.execute('''
                                INSERT INTO Questions (quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks, module)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ''', (quiz_id, question_text, option_a, option_b, option_c, option_d, correct, marks, module_name))
                            questions_added += 1
            else:
                # Fallback: parse paragraphs
                current_question = None
                current_options = {}
                current_correct = 'A'
                current_marks = 1
                
                def save_question():
                    nonlocal questions_added
                    if current_question and current_options:
                        cursor.execute('''
                            INSERT INTO Questions (quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option, marks, module)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ''', (quiz_id, current_question, 
                              current_options.get('A', ''), current_options.get('B', ''), 
                              current_options.get('C', ''), current_options.get('D', ''),
                              current_correct, current_marks, module_name))
                        questions_added += 1
                
                for para in doc.paragraphs:
                    text = para.text.strip()
                    if not text:
                        continue
                    
                    is_new_question = False
                    if text[0].isdigit() and (text[1:].startswith('.') or text[1:].startswith(')')):
                        is_new_question = True
                    elif len(text) < 100 and not any(x in text.upper() for x in ['OPTION', 'ANSWER', 'CORRECT']):
                        is_new_question = True
                    
                    if is_new_question and current_question:
                        save_question()
                        current_question = None
                        current_options = {}
                        current_correct = 'A'
                    
                    if not current_question:
                        current_question = text
                    else:
                        line = text.strip()
                        upper_line = line.upper()
                        
                        if line.startswith('A)') or line.startswith('A.'):
                            current_options['A'] = line[2:].strip() if len(line) > 2 else ''
                        elif line.startswith('B)') or line.startswith('B.'):
                            current_options['B'] = line[2:].strip() if len(line) > 2 else ''
                        elif line.startswith('C)') or line.startswith('C.'):
                            current_options['C'] = line[2:].strip() if len(line) > 2 else ''
                        elif line.startswith('D)') or line.startswith('D.'):
                            current_options['D'] = line[2:].strip() if len(line) > 2 else ''
                        elif 'ANSWER:' in upper_line or 'CORRECT:' in upper_line:
                            for opt in ['A', 'B', 'C', 'D']:
                                if opt in upper_line:
                                    current_correct = opt
                                    break
                        elif upper_line.startswith('MARKS:') or upper_line.startswith('MARK:'):
                            try:
                                current_marks = int(''.join(filter(str.isdigit, line)))
                            except:
                                current_marks = 1
                
                if current_question:
                    save_question()
            
            conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'count': questions_added})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug_mode, use_reloader=False, port=5000)
