import os
import sys
import json
import csv
import io
import zipfile
import tempfile
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, send_file, flash, redirect, url_for, session
from database import get_db_connection
from code_runner import execute_code
from utils import normalize_judge_output

try:
    import docx
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
except ImportError:
    docx = None

coding_bp = Blueprint('coding', __name__, url_prefix='/admin/coding')

@coding_bp.before_request
def check_coding_admin():
    if not session.get('user_id') or session.get('role') not in ['Admin', 'Coordinator']:
        if request.path.startswith('/admin/coding/api/') or request.method == 'POST':
            return jsonify({'success': False, 'error': 'Access denied. Admin or Coordinator role required.'}), 403
        flash('Access denied. Admin or Coordinator role required.', 'error')
        return redirect(url_for('auth.login'))

# Supported languages & boilerplates
SUPPORTED_LANGUAGES = ['python', 'c', 'cpp', 'java', 'javascript']

DEFAULT_BOILERPLATES = {
    'python': (
        "import sys\n\n"
        "def solve():\n"
        "    input_data = sys.stdin.read().split()\n"
        "    if not input_data:\n"
        "        return\n"
        "    # Write your solution here\n"
        "    a = int(input_data[0])\n"
        "    b = int(input_data[1])\n"
        "    print(a + b)\n\n"
        "if __name__ == '__main__':\n"
        "    solve()\n"
    ),
    'cpp': (
        "#include <iostream>\n"
        "using namespace std;\n\n"
        "int main() {\n"
        "    ios_base::sync_with_stdio(false);\n"
        "    cin.tie(NULL);\n"
        "    // Write your solution here\n"
        "    int a, b;\n"
        "    if (cin >> a >> b) {\n"
        "        cout << (a + b) << \"\\n\";\n"
        "    }\n"
        "    return 0;\n"
        "}\n"
    ),
    'c': (
        "#include <stdio.h>\n\n"
        "int main() {\n"
        "    // Write your solution here\n"
        "    int a, b;\n"
        "    if (scanf(\"%d %d\", &a, &b) == 2) {\n"
        "        printf(\"%d\\n\", a + b);\n"
        "    }\n"
        "    return 0;\n"
        "}\n"
    ),
    'java': (
        "import java.util.Scanner;\n\n"
        "public class Main {\n"
        "    public static void main(String[] args) {\n"
        "        Scanner sc = new Scanner(System.in);\n"
        "        // Write your solution here\n"
        "        if (sc.hasNextInt()) {\n"
        "            int a = sc.nextInt();\n"
        "            int b = sc.nextInt();\n"
        "            System.out.println(a + b);\n"
        "        }\n"
        "    }\n"
        "}\n"
    ),
    'javascript': (
        "const fs = require('fs');\n\n"
        "function solve() {\n"
        "    const input = fs.readFileSync(0, 'utf8').trim().split(/\\s+/);\n"
        "    if (input.length < 2) return;\n"
        "    // Write your solution here\n"
        "    const a = parseInt(input[0], 10);\n"
        "    const b = parseInt(input[1], 10);\n"
        "    console.log(a + b);\n"
        "}\n\n"
        "solve();\n"
    )
}

DEFAULT_EVALUATION_SETTINGS = {
    'exactOutput': True,
    'ignoreLeadingTrailingWhitespace': True,
    'ignoreLineEndingDifferences': True,
    'caseSensitive': True,
    'partialScoring': True,
    'allowCustomInput': True
}

# --- VALIDATION SERVICE ---
class CodingQuestionValidationService:
    @staticmethod
    def normalize_difficulty(val):
        if not val:
            return 'Easy'
        v = str(val).strip().lower()
        if v in ('easy', 'e'):
            return 'Easy'
        elif v in ('medium', 'med', 'm'):
            return 'Medium'
        elif v in ('difficult', 'hard', 'diff', 'd', 'h'):
            return 'Difficult'
        return 'Easy'

    @staticmethod
    def validate_question(q_dict, index=1):
        errors = []
        field_errors = {}

        title = (q_dict.get('title') or '').strip()
        if not title:
            field_errors['title'] = 'Question title is required.'
            errors.append(f'Question {index}: Missing question title.')

        problem = (q_dict.get('problemStatement') or q_dict.get('question_text') or '').strip()
        if not problem:
            field_errors['problemStatement'] = 'Problem statement is required.'
            errors.append(f'Question {index}: Missing problem statement.')

        # Supported languages
        langs = q_dict.get('supportedLanguages')
        if isinstance(langs, str):
            langs = [x.strip().lower() for x in langs.split(',') if x.strip()]
        elif isinstance(langs, list):
            langs = [str(x).strip().lower() for x in langs if str(x).strip()]
        else:
            langs = ['python']

        invalid_langs = [l for l in langs if l not in SUPPORTED_LANGUAGES]
        if invalid_langs:
            field_errors['supportedLanguages'] = f"Unsupported programming language(s): {', '.join(invalid_langs)}"
            errors.append(f"Question {index}: Unsupported programming language(s): {', '.join(invalid_langs)}")

        if not langs:
            langs = ['python']

        # Marks & Negative marks
        try:
            marks = float(q_dict.get('marks', 10))
            if marks <= 0:
                field_errors['marks'] = 'Marks must be greater than 0.'
                errors.append(f'Question {index}: Marks must be greater than 0.')
        except (ValueError, TypeError):
            field_errors['marks'] = 'Marks must be a valid number.'
            errors.append(f'Question {index}: Invalid marks value.')

        try:
            neg_marks = float(q_dict.get('negativeMarks', q_dict.get('negative_marks', 0)))
            if neg_marks < 0:
                field_errors['negativeMarks'] = 'Negative marks cannot be negative.'
                errors.append(f'Question {index}: Negative marks cannot be negative.')
        except (ValueError, TypeError):
            field_errors['negativeMarks'] = 'Negative marks must be a valid number.'
            errors.append(f'Question {index}: Invalid negative marks value.')

        # Test cases validation
        test_cases = q_dict.get('testCases') or []
        if isinstance(test_cases, str):
            try:
                test_cases = json.loads(test_cases)
            except Exception:
                test_cases = []

        valid_tc = []
        for tc_idx, tc in enumerate(test_cases, 1):
            if not isinstance(tc, dict):
                continue
            inp = str(tc.get('input', ''))
            exp = str(tc.get('expectedOutput', tc.get('output', '')))
            if exp == '' and inp == '':
                field_errors[f'testCase_{tc_idx}'] = f'Test case {tc_idx} is empty.'
                errors.append(f'Question {index}: Test case {tc_idx} has neither input nor expected output.')
            valid_tc.append({
                'id': tc.get('id') or f'tc_{tc_idx:03d}',
                'input': inp,
                'expectedOutput': exp,
                'hidden': bool(tc.get('hidden', False)),
                'weight': float(tc.get('weight', 20) or 20),
                'explanation': str(tc.get('explanation', '') or '')
            })

        diff_norm = CodingQuestionValidationService.normalize_difficulty(q_dict.get('difficulty'))

        normalized_q = {
            'id': str(q_dict.get('id') or q_dict.get('question_id') or f"code_{index:03d}"),
            'title': title or 'Untitled Coding Challenge',
            'problemStatement': problem,
            'detailedDescription': str(q_dict.get('detailedDescription') or ''),
            'difficulty': diff_norm,
            'category': str(q_dict.get('category') or 'Coding Challenges').strip(),
            'tags': q_dict.get('tags') if isinstance(q_dict.get('tags'), list) else [t.strip() for t in str(q_dict.get('tags', '')).split(',') if t.strip()],
            'marks': float(q_dict.get('marks', 10)),
            'negativeMarks': float(q_dict.get('negativeMarks', q_dict.get('negative_marks', 0))),
            'timeLimitMs': int(q_dict.get('timeLimitMs', 2000) or 2000),
            'memoryLimitMb': int(q_dict.get('memoryLimitMb', 256) or 256),
            'status': str(q_dict.get('status') or 'draft').strip().lower(),
            'supportedLanguages': langs,
            'starterCode': q_dict.get('starterCode') if isinstance(q_dict.get('starterCode'), dict) else DEFAULT_BOILERPLATES,
            'inputFormat': str(q_dict.get('inputFormat') or ''),
            'outputFormat': str(q_dict.get('outputFormat') or ''),
            'constraints': q_dict.get('constraints') if isinstance(q_dict.get('constraints'), list) else ([str(q_dict.get('constraints'))] if q_dict.get('constraints') else []),
            'samples': q_dict.get('samples') if isinstance(q_dict.get('samples'), list) else [],
            'testCases': valid_tc,
            'evaluationSettings': q_dict.get('evaluationSettings') if isinstance(q_dict.get('evaluationSettings'), dict) else DEFAULT_EVALUATION_SETTINGS,
            'explanation': str(q_dict.get('explanation') or '')
        }

        is_valid = len(errors) == 0
        return {
            'is_valid': is_valid,
            'errors': errors,
            'field_errors': field_errors,
            'data': normalized_q
        }


# --- CODE EVALUATION SERVICE ---
class CodeEvaluationService:
    @staticmethod
    def compare_output(actual, expected, settings=None):
        if settings is None:
            settings = DEFAULT_EVALUATION_SETTINGS

        act = actual or ''
        exp = expected or ''

        if settings.get('ignoreLineEndingDifferences', True):
            act = act.replace('\r\n', '\n').replace('\r', '\n')
            exp = exp.replace('\r\n', '\n').replace('\r', '\n')

        if settings.get('ignoreLeadingTrailingWhitespace', True):
            # Strip outer and per line trailing whitespace
            act = '\n'.join([line.rstrip() for line in act.strip().split('\n')])
            exp = '\n'.join([line.rstrip() for line in exp.strip().split('\n')])

        if not settings.get('caseSensitive', True):
            act = act.lower()
            exp = exp.lower()

        return act == exp

    @staticmethod
    def run_tests(code, language, test_cases, evaluation_settings=None, time_limit_ms=2000, mask_hidden=False):
        if evaluation_settings is None:
            evaluation_settings = DEFAULT_EVALUATION_SETTINGS

        timeout_sec = max(1.0, float(time_limit_ms) / 1000.0)
        results = []
        passed_count = 0
        total_weight = 0
        earned_weight = 0
        first_error = None

        for idx, tc in enumerate(test_cases, 1):
            tc_input = tc.get('input', '')
            expected_out = tc.get('expectedOutput', '')
            is_hidden = bool(tc.get('hidden', False))
            weight = float(tc.get('weight', 20) or 20)
            total_weight += weight

            t_start = datetime.now()
            exec_res = execute_code(code, language, stdin_data=tc_input, timeout=timeout_sec)
            t_duration = round((datetime.now() - t_start).total_seconds() * 1000, 1)

            stdout = exec_res.get('stdout', '')
            stderr = exec_res.get('stderr', '')
            verdict = exec_res.get('verdict', 'Runtime Error')

            if verdict == 'Accepted':
                is_match = CodeEvaluationService.compare_output(stdout, expected_out, evaluation_settings)
                if is_match:
                    case_status = 'Passed'
                    passed_count += 1
                    earned_weight += weight
                else:
                    case_status = 'Wrong Answer'
                    if not first_error:
                        first_error = 'Wrong Answer'
            else:
                case_status = verdict
                if not first_error:
                    first_error = verdict

            res_item = {
                'id': tc.get('id', f'tc_{idx}'),
                'caseIndex': idx,
                'status': case_status,
                'passed': (case_status == 'Passed'),
                'timeMs': t_duration,
                'hidden': is_hidden,
                'weight': weight
            }

            if mask_hidden and is_hidden:
                res_item['input'] = '[Hidden Test Case]'
                res_item['expectedOutput'] = '[Hidden Expected Output]'
                res_item['actualOutput'] = '[Hidden Output]'
            else:
                res_item['input'] = tc_input
                res_item['expectedOutput'] = expected_out
                res_item['actualOutput'] = stdout
                if stderr:
                    res_item['stderr'] = stderr

            results.append(res_item)

        total_cases = len(test_cases)
        overall_status = 'Accepted' if (total_cases > 0 and passed_count == total_cases) else (first_error or 'Wrong Answer')
        score_pct = (earned_weight / total_weight * 100.0) if total_weight > 0 else (100.0 if passed_count == total_cases else 0.0)

        return {
            'overallStatus': overall_status,
            'passedCount': passed_count,
            'totalCount': total_cases,
            'scorePercentage': round(score_pct, 1),
            'earnedWeight': earned_weight,
            'totalWeight': total_weight,
            'cases': results
        }


# --- DATABASE HELPERS ---
def format_row_to_coding_dict(row):
    """Parses Questions row into full coding challenge dictionary."""
    meta = {}
    if row.get('metadata_json'):
        try:
            if isinstance(row['metadata_json'], str):
                meta = json.loads(row['metadata_json'])
            elif isinstance(row['metadata_json'], dict):
                meta = row['metadata_json']
        except Exception:
            meta = {}

    # Extract test cases
    test_cases = meta.get('testCases') or []
    if not test_cases and (row.get('test_input') or row.get('test_output')):
        from utils import split_test_case_block
        inps = split_test_case_block(row.get('test_input'))
        outs = split_test_case_block(row.get('test_output'))
        for i in range(max(len(inps), len(outs))):
            test_cases.append({
                'id': f'tc_{i+1:03d}',
                'input': inps[i] if i < len(inps) else '',
                'expectedOutput': outs[i] if i < len(outs) else '',
                'hidden': i > 0,
                'weight': 20,
                'explanation': 'Migrated test case'
            })

    # Starter code
    starter_code = meta.get('starterCode') or DEFAULT_BOILERPLATES

    # Supported languages
    supported_langs = meta.get('supportedLanguages') or ['python', 'c', 'cpp', 'java', 'javascript']

    # Evaluation settings
    eval_settings = meta.get('evaluationSettings') or DEFAULT_EVALUATION_SETTINGS

    title = meta.get('title') or (row.get('question_text', '').split('\n')[0][:80] if row.get('question_text') else f"Question {row.get('question_id')}")

    diff_norm = CodingQuestionValidationService.normalize_difficulty(row.get('difficulty') or meta.get('difficulty'))

    return {
        'question_id': row.get('question_id'),
        'id': meta.get('id') or f"code_{row.get('question_id')}",
        'quiz_id': row.get('quiz_id'),
        'title': title,
        'problemStatement': meta.get('problemStatement') or row.get('question_text') or '',
        'detailedDescription': meta.get('detailedDescription') or '',
        'difficulty': diff_norm,
        'category': row.get('category') or meta.get('category') or 'Coding Challenges',
        'tags': meta.get('tags') or ([t.strip() for t in row.get('tags', '').split(',') if t.strip()] if row.get('tags') else []),
        'marks': float(row.get('marks') or 10),
        'negativeMarks': float(row.get('negative_marks') or 0),
        'timeLimitMs': int(meta.get('timeLimitMs') or 2000),
        'memoryLimitMb': int(meta.get('memoryLimitMb') or 256),
        'status': row.get('status') or meta.get('status') or 'published',
        'supportedLanguages': supported_langs,
        'starterCode': starter_code,
        'inputFormat': meta.get('inputFormat') or '',
        'outputFormat': meta.get('outputFormat') or '',
        'constraints': meta.get('constraints') or [],
        'samples': meta.get('samples') or [],
        'testCases': test_cases,
        'evaluationSettings': eval_settings,
        'explanation': row.get('explanation') or meta.get('explanation') or '',
        'created_at': str(row.get('created_at') or ''),
        'updated_at': str(row.get('updated_at') or '')
    }


def format_test_case_block(cases):
    if not cases:
        return ''
    return '\n---\n'.join([str(c or '').strip() for c in cases])

def save_coding_question_to_db(q_data, quiz_id=None, question_id=None):
    """Inserts or updates a coding question in the database."""
    conn = get_db_connection()
    with conn.cursor() as cursor:
        diff_norm = CodingQuestionValidationService.normalize_difficulty(q_data.get('difficulty'))
        
        # Build test_input and test_output blocks
        tc_list = q_data.get('testCases') or []
        inp_list = [tc.get('input', '') for tc in tc_list]
        out_list = [tc.get('expectedOutput', '') for tc in tc_list]
        test_in_block = format_test_case_block(inp_list)
        test_out_block = format_test_case_block(out_list)

        # Meta payload
        meta_payload = {
            'id': q_data.get('id') or f"code_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'title': q_data.get('title'),
            'problemStatement': q_data.get('problemStatement'),
            'detailedDescription': q_data.get('detailedDescription', ''),
            'difficulty': diff_norm,
            'category': q_data.get('category', 'Coding Challenges'),
            'tags': q_data.get('tags', []),
            'marks': q_data.get('marks', 10),
            'negativeMarks': q_data.get('negativeMarks', 0),
            'timeLimitMs': q_data.get('timeLimitMs', 2000),
            'memoryLimitMb': q_data.get('memoryLimitMb', 256),
            'status': q_data.get('status', 'draft'),
            'supportedLanguages': q_data.get('supportedLanguages', SUPPORTED_LANGUAGES),
            'starterCode': q_data.get('starterCode', DEFAULT_BOILERPLATES),
            'inputFormat': q_data.get('inputFormat', ''),
            'outputFormat': q_data.get('outputFormat', ''),
            'constraints': q_data.get('constraints', []),
            'samples': q_data.get('samples', []),
            'testCases': tc_list,
            'evaluationSettings': q_data.get('evaluationSettings', DEFAULT_EVALUATION_SETTINGS),
            'explanation': q_data.get('explanation', '')
        }
        meta_json_str = json.dumps(meta_payload)

        q_quiz_id = quiz_id if quiz_id is not None else q_data.get('quiz_id')
        cursor.execute('SELECT quiz_id FROM Quizzes WHERE quiz_id = %s', (q_quiz_id,))
        if not cursor.fetchone():
            cursor.execute('SELECT quiz_id FROM Quizzes ORDER BY quiz_id ASC LIMIT 1')
            q_row = cursor.fetchone()
            if q_row:
                q_quiz_id = q_row['quiz_id']
            else:
                cursor.execute("INSERT INTO Quizzes (title, batch, department, total_marks, duration) VALUES ('Coding Challenges', 'All', 'General', 100, 60)")
                cursor.execute('SELECT quiz_id FROM Quizzes ORDER BY quiz_id DESC LIMIT 1')
                q_row = cursor.fetchone()
                q_quiz_id = q_row['quiz_id'] if q_row else 1

        tags_str = ', '.join(q_data.get('tags', [])) if isinstance(q_data.get('tags'), list) else str(q_data.get('tags', ''))

        if question_id:
            cursor.execute('''
                UPDATE Questions SET
                    quiz_id=%s,
                    question_text=%s,
                    question_type='coding',
                    module='Coding',
                    difficulty=%s,
                    category=%s,
                    tags=%s,
                    marks=%s,
                    negative_marks=%s,
                    test_input=%s,
                    test_output=%s,
                    metadata_json=%s,
                    status=%s,
                    explanation=%s,
                    updated_at=NOW()
                WHERE question_id=%s
            ''', (
                q_quiz_id,
                q_data.get('problemStatement', ''),
                diff_norm,
                q_data.get('category', 'Coding Challenges'),
                tags_str,
                q_data.get('marks', 10),
                q_data.get('negativeMarks', 0),
                test_in_block,
                test_out_block,
                meta_json_str,
                q_data.get('status', 'draft'),
                q_data.get('explanation', ''),
                question_id
            ))
            saved_id = question_id
        else:
            cursor.execute('''
                INSERT INTO Questions (
                    quiz_id, question_text, question_type, module,
                    difficulty, category, tags, marks, negative_marks,
                    test_input, test_output, metadata_json, status,
                    explanation, created_at, updated_at
                ) VALUES (
                    %s, %s, 'coding', 'Coding',
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, NOW(), NOW()
                )
            ''', (
                q_quiz_id,
                q_data.get('problemStatement', ''),
                diff_norm,
                q_data.get('category', 'Coding Challenges'),
                tags_str,
                q_data.get('marks', 10),
                q_data.get('negativeMarks', 0),
                test_in_block,
                test_out_block,
                meta_json_str,
                q_data.get('status', 'draft'),
                q_data.get('explanation', '')
            ))
            saved_id = cursor.lastrowid
            if not saved_id:
                cursor.execute('SELECT question_id FROM Questions ORDER BY question_id DESC LIMIT 1')
                last_q = cursor.fetchone()
                saved_id = last_q['question_id'] if last_q else None

    conn.commit()
    conn.close()
    return saved_id


# --- ROUTE HANDLERS ---

@coding_bp.route('', methods=['GET'])
@coding_bp.route('/', methods=['GET'])
def coding_builder():
    """Main Coding Question Builder workspace."""
    conn = get_db_connection()
    if not conn:
        flash('Database connection error.', 'error')
        return redirect('/admin')

    sessions_list = []
    q_rows = []
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT quiz_id, title FROM Quizzes ORDER BY quiz_id DESC')
            sessions_list = cursor.fetchall()

            # Get all coding questions
            cursor.execute('''
                SELECT * FROM Questions 
                WHERE question_type='coding' OR module='Coding'
                ORDER BY question_id DESC
            ''')
            q_rows = cursor.fetchall()
    except Exception as e:
        flash(f'Error loading coding questions: {str(e)}', 'error')
    finally:
        conn.close()

    questions = [format_row_to_coding_dict(r) for r in q_rows]

    # Calculate summary metrics
    total_q = len(questions)
    easy_q = sum(1 for q in questions if q['difficulty'] == 'Easy')
    medium_q = sum(1 for q in questions if q['difficulty'] == 'Medium')
    diff_q = sum(1 for q in questions if q['difficulty'] == 'Difficult')
    published_q = sum(1 for q in questions if q['status'] == 'published')
    draft_q = sum(1 for q in questions if q['status'] == 'draft')

    metrics = {
        'total': total_q,
        'easy': easy_q,
        'medium': medium_q,
        'difficult': diff_q,
        'published': published_q,
        'draft': draft_q
    }

    return render_template(
        'coding_builder.html',
        sessions=sessions_list,
        questions=questions,
        metrics=metrics,
        default_boilerplates=DEFAULT_BOILERPLATES,
        supported_languages=SUPPORTED_LANGUAGES
    )


@coding_bp.route('/api/list', methods=['GET'])
def api_list_questions():
    """Returns JSON list of coding questions with filters."""
    quiz_id = request.args.get('quiz_id')
    difficulty = request.args.get('difficulty')
    status = request.args.get('status')
    search = request.args.get('search', '').strip().lower()

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('''
            SELECT * FROM Questions 
            WHERE question_type='coding' OR module='Coding'
            ORDER BY question_id DESC
        ''')
        rows = cursor.fetchall()
    conn.close()

    questions = [format_row_to_coding_dict(r) for r in rows]

    filtered = []
    for q in questions:
        if quiz_id and str(q['quiz_id']) != str(quiz_id):
            continue
        if difficulty and difficulty.lower() != 'all':
            if q['difficulty'].lower() != difficulty.lower():
                continue
        if status and status.lower() != 'all':
            if q['status'].lower() != status.lower():
                continue
        if search:
            match_title = search in q['title'].lower()
            match_prob = search in q['problemStatement'].lower()
            match_cat = search in q['category'].lower()
            if not (match_title or match_prob or match_cat):
                continue
        filtered.append(q)

    return jsonify({'success': True, 'count': len(filtered), 'questions': filtered})


@coding_bp.route('/api/get/<int:question_id>', methods=['GET'])
def api_get_question(question_id):
    """Return single coding question details."""
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('SELECT * FROM Questions WHERE question_id=%s', (question_id,))
        row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({'success': False, 'error': 'Question not found'}), 404

    q_data = format_row_to_coding_dict(row)
    return jsonify({'success': True, 'question': q_data})


@coding_bp.route('/save', methods=['POST'])
def api_save_question():
    """Create or update a coding question."""
    payload = request.json
    if not payload:
        return jsonify({'success': False, 'error': 'Invalid JSON request.'}), 400

    q_id = payload.get('question_id')
    quiz_id = payload.get('quiz_id')

    validation = CodingQuestionValidationService.validate_question(payload)
    if not validation['is_valid']:
        return jsonify({
            'success': False,
            'error': 'Validation failed.',
            'errors': validation['errors'],
            'field_errors': validation['field_errors']
        }), 422

    try:
        saved_id = save_coding_question_to_db(validation['data'], quiz_id=quiz_id, question_id=q_id)
        return jsonify({
            'success': True,
            'message': 'Coding question saved successfully!',
            'question_id': saved_id
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'Database error: {str(e)}'}), 500


@coding_bp.route('/delete/<int:question_id>', methods=['POST'])
def api_delete_question(question_id):
    """Deletes a coding question."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM Quiz_Responses WHERE question_id=%s', (question_id,))
            cursor.execute('DELETE FROM Questions WHERE question_id=%s', (question_id,))
        conn.commit()
        return jsonify({'success': True, 'message': 'Question deleted successfully.'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()


@coding_bp.route('/duplicate/<int:question_id>', methods=['POST'])
def api_duplicate_question(question_id):
    """Duplicates a coding question."""
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('SELECT * FROM Questions WHERE question_id=%s', (question_id,))
        row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({'success': False, 'error': 'Question not found'}), 404

    q_dict = format_row_to_coding_dict(row)
    q_dict['title'] = f"{q_dict['title']} (Copy)"
    q_dict['id'] = f"{q_dict['id']}_copy"
    q_dict['status'] = 'draft'

    try:
        new_id = save_coding_question_to_db(q_dict, quiz_id=q_dict['quiz_id'])
        return jsonify({'success': True, 'message': 'Question duplicated successfully.', 'new_question_id': new_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@coding_bp.route('/status/<int:question_id>', methods=['POST'])
def api_toggle_status(question_id):
    """Toggles status between published and draft."""
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('SELECT status, metadata_json FROM Questions WHERE question_id=%s', (question_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({'success': False, 'error': 'Question not found'}), 404

        cur_status = row.get('status') or 'draft'
        new_status = 'draft' if cur_status == 'published' else 'published'

        meta = {}
        if row.get('metadata_json'):
            try:
                meta = json.loads(row['metadata_json'])
            except Exception:
                meta = {}
        meta['status'] = new_status

        cursor.execute('UPDATE Questions SET status=%s, metadata_json=%s WHERE question_id=%s', (
            new_status, json.dumps(meta), question_id
        ))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'new_status': new_status})


@coding_bp.route('/api/run_test', methods=['POST'])
def api_run_test():
    """
    Executes code against test cases or custom input.
    """
    payload = request.json or {}
    code = payload.get('code', '')
    language = payload.get('language', 'python').lower()
    mode = payload.get('mode', 'test_cases') # 'test_cases' or 'custom'
    eval_settings = payload.get('evaluationSettings', DEFAULT_EVALUATION_SETTINGS)
    time_limit_ms = int(payload.get('timeLimitMs', 2000) or 2000)
    mask_hidden = bool(payload.get('mask_hidden', False))

    if not code.strip():
        return jsonify({'success': False, 'error': 'Code cannot be empty.'}), 400

    if mode == 'custom':
        custom_stdin = payload.get('stdin', '')
        timeout_sec = max(1.0, float(time_limit_ms) / 1000.0)
        t_start = datetime.now()
        exec_res = execute_code(code, language, stdin_data=custom_stdin, timeout=timeout_sec)
        t_duration = round((datetime.now() - t_start).total_seconds() * 1000, 1)

        return jsonify({
            'success': True,
            'mode': 'custom',
            'verdict': exec_res.get('verdict', 'Accepted'),
            'stdout': exec_res.get('stdout', ''),
            'stderr': exec_res.get('stderr', ''),
            'timeMs': t_duration
        })

    # Test cases mode
    test_cases = payload.get('testCases', [])
    if not test_cases:
        return jsonify({'success': False, 'error': 'No test cases provided for execution.'}), 400

    summary = CodeEvaluationService.run_tests(
        code, language, test_cases,
        evaluation_settings=eval_settings,
        time_limit_ms=time_limit_ms,
        mask_hidden=mask_hidden
    )

    return jsonify({'success': True, 'mode': 'test_cases', 'summary': summary})


@coding_bp.route('/api/bulk_create', methods=['POST'])
def api_bulk_create():
    """Bulk create multiple coding questions in one transaction."""
    payload = request.json or {}
    questions_data = payload.get('questions', [])
    quiz_id = payload.get('quiz_id')

    if not questions_data or not isinstance(questions_data, list):
        return jsonify({'success': False, 'error': 'No questions list provided.'}), 400

    validated_list = []
    all_errors = []

    for idx, q_item in enumerate(questions_data, 1):
        v = CodingQuestionValidationService.validate_question(q_item, index=idx)
        if not v['is_valid']:
            all_errors.append({
                'index': idx,
                'title': q_item.get('title', f'Question {idx}'),
                'errors': v['errors'],
                'field_errors': v['field_errors']
            })
        else:
            validated_list.append(v['data'])

    if all_errors:
        return jsonify({
            'success': False,
            'message': f'{len(all_errors)} question(s) failed validation.',
            'validation_failures': all_errors
        }), 422

    # Commit all in single transaction
    saved_ids = []
    try:
        for q_data in validated_list:
            s_id = save_coding_question_to_db(q_data, quiz_id=quiz_id)
            saved_ids.append(s_id)
        return jsonify({
            'success': True,
            'message': f'Successfully created {len(saved_ids)} coding questions!',
            'created_ids': saved_ids
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'Transaction error: {str(e)}'}), 500


# --- BULK IMPORT (JSON, CSV, DOCX, ZIP) ---

def parse_coding_json(content_bytes):
    """Parses coding questions from JSON format."""
    text = content_bytes.decode('utf-8', errors='replace')
    data = json.loads(text)
    if isinstance(data, dict):
        if 'questions' in data and isinstance(data['questions'], list):
            return data['questions']
        return [data]
    elif isinstance(data, list):
        return data
    return []


def parse_coding_csv(content_bytes):
    """Parses coding questions from CSV format."""
    text = content_bytes.decode('utf-8', errors='replace')
    reader = csv.DictReader(io.StringIO(text))
    questions = []

    for row in reader:
        # Starter code
        starter_code = DEFAULT_BOILERPLATES.copy()
        if row.get('starterCode'):
            try:
                parsed_sc = json.loads(row['starterCode'])
                if isinstance(parsed_sc, dict):
                    starter_code.update(parsed_sc)
            except Exception:
                starter_code['python'] = row['starterCode']

        # Test cases
        test_cases = []
        if row.get('testCases'):
            try:
                tc_data = json.loads(row['testCases'])
                if isinstance(tc_data, list):
                    test_cases = tc_data
            except Exception:
                pass

        # Samples
        samples = []
        if row.get('samples'):
            try:
                samp_data = json.loads(row['samples'])
                if isinstance(samp_data, list):
                    samples = samp_data
            except Exception:
                pass

        # Constraints
        constraints = []
        if row.get('constraints'):
            try:
                con_data = json.loads(row['constraints'])
                if isinstance(con_data, list):
                    constraints = con_data
            except Exception:
                constraints = [row['constraints']]

        # Languages
        langs = [l.strip().lower() for l in (row.get('supportedLanguages') or 'python,c,cpp,java,javascript').split(',') if l.strip()]

        questions.append({
            'id': row.get('id'),
            'title': row.get('title'),
            'difficulty': CodingQuestionValidationService.normalize_difficulty(row.get('difficulty')),
            'category': row.get('category', 'Coding Challenges'),
            'tags': [t.strip() for t in (row.get('tags') or '').split(',') if t.strip()],
            'problemStatement': row.get('problemStatement', ''),
            'inputFormat': row.get('inputFormat', ''),
            'outputFormat': row.get('outputFormat', ''),
            'constraints': constraints,
            'supportedLanguages': langs,
            'starterCode': starter_code,
            'samples': samples,
            'testCases': test_cases,
            'marks': float(row.get('marks') or 10),
            'negativeMarks': float(row.get('negativeMarks') or 0),
            'timeLimitMs': int(row.get('timeLimitMs') or 2000),
            'memoryLimitMb': int(row.get('memoryLimitMb') or 256),
            'status': row.get('status', 'draft')
        })

    return questions


def parse_coding_docx(content_bytes):
    """Parses coding questions from Word (.docx) document."""
    if not docx:
        raise RuntimeError("python-docx is not installed.")

    doc = docx.Document(io.BytesIO(content_bytes))
    questions = []

    # Iterate through tables in docx
    for table in doc.tables:
        q_dict = {
            'starterCode': DEFAULT_BOILERPLATES.copy(),
            'samples': [],
            'testCases': [],
            'constraints': [],
            'supportedLanguages': ['python', 'c', 'cpp', 'java', 'javascript']
        }
        for row in table.rows:
            if len(row.cells) >= 2:
                key = row.cells[0].text.strip().lower()
                val = row.cells[1].text.strip()

                if 'id' in key:
                    q_dict['id'] = val
                elif 'title' in key:
                    q_dict['title'] = val
                elif 'difficulty' in key:
                    q_dict['difficulty'] = CodingQuestionValidationService.normalize_difficulty(val)
                elif 'category' in key:
                    q_dict['category'] = val
                elif 'problem' in key or 'statement' in key or 'question' in key:
                    q_dict['problemStatement'] = val
                elif 'input format' in key:
                    q_dict['inputFormat'] = val
                elif 'output format' in key:
                    q_dict['outputFormat'] = val
                elif 'constraint' in key:
                    q_dict['constraints'] = [c.strip() for c in val.split('\n') if c.strip()]
                elif 'language' in key:
                    q_dict['supportedLanguages'] = [l.strip().lower() for l in val.split(',') if l.strip()]
                elif 'starter' in key or 'boilerplate' in key:
                    try:
                        q_dict['starterCode'] = json.loads(val)
                    except Exception:
                        q_dict['starterCode']['python'] = val
                elif 'sample' in key:
                    # Parse sample input / output
                    try:
                        q_dict['samples'] = json.loads(val)
                    except Exception:
                        q_dict['samples'] = [{'input': val, 'expectedOutput': '', 'explanation': ''}]
                elif 'test case' in key or 'testcase' in key:
                    try:
                        q_dict['testCases'] = json.loads(val)
                    except Exception:
                        pass
                elif 'negative' in key:
                    try:
                        q_dict['negativeMarks'] = float(val)
                    except Exception:
                        pass
                elif 'mark' in key:
                    try:
                        q_dict['marks'] = float(val)
                    except Exception:
                        pass
                elif 'time' in key:
                    try:
                        q_dict['timeLimitMs'] = int(val)
                    except Exception:
                        pass
                elif 'memory' in key:
                    try:
                        q_dict['memoryLimitMb'] = int(val)
                    except Exception:
                        pass
                elif 'status' in key:
                    q_dict['status'] = val.lower()

        if q_dict.get('title') or q_dict.get('problemStatement'):
            questions.append(q_dict)

    # If no tables found, try paragraph parsing
    if not questions:
        current_q = {}
        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                continue
            if text.lower().startswith('question ') or text.lower().startswith('problem '):
                if current_q.get('title') or current_q.get('problemStatement'):
                    questions.append(current_q)
                current_q = {'title': text, 'starterCode': DEFAULT_BOILERPLATES.copy(), 'testCases': [], 'samples': []}
            elif ':' in text:
                k, v = text.split(':', 1)
                k = k.strip().lower()
                v = v.strip()
                if 'title' in k:
                    current_q['title'] = v
                elif 'difficulty' in k:
                    current_q['difficulty'] = CodingQuestionValidationService.normalize_difficulty(v)
                elif 'problem' in k or 'statement' in k:
                    current_q['problemStatement'] = v
                elif 'input' in k:
                    current_q['inputFormat'] = v
                elif 'output' in k:
                    current_q['outputFormat'] = v
                elif 'marks' in k:
                    try: current_q['marks'] = float(v)
                    except Exception: pass
        if current_q.get('title') or current_q.get('problemStatement'):
            questions.append(current_q)

    return questions


def parse_coding_zip(content_bytes):
    """Parses coding questions from ZIP package."""
    questions = []
    with zipfile.ZipFile(io.BytesIO(content_bytes), 'r') as zf:
        file_list = zf.namelist()
        
        # 1. Check if questions.json exists
        json_files = [f for f in file_list if f.endswith('.json') and not f.startswith('__MACOSX')]
        if json_files:
            target_json = 'questions.json' if 'questions.json' in json_files else json_files[0]
            with zf.open(target_json) as f:
                questions = parse_coding_json(f.read())
        else:
            # Check for CSV
            csv_files = [f for f in file_list if f.endswith('.csv') and not f.startswith('__MACOSX')]
            if csv_files:
                with zf.open(csv_files[0]) as f:
                    questions = parse_coding_csv(f.read())

        # Check for external testcase files (.in, .out)
        for q in questions:
            q_id = q.get('id')
            if not q_id:
                continue
            tc_list = q.get('testCases', [])
            # Search for files like {q_id}_tc1.in, {q_id}_tc1.out
            matching_in = sorted([f for f in file_list if f.startswith(f"{q_id}_") and f.endswith('.in')])
            for m_in in matching_in:
                base = m_in[:-3]
                m_out = f"{base}.out"
                if m_out in file_list:
                    with zf.open(m_in) as fi, zf.open(m_out) as fo:
                        tc_list.append({
                            'id': os.path.basename(base),
                            'input': fi.read().decode('utf-8', errors='replace'),
                            'expectedOutput': fo.read().decode('utf-8', errors='replace'),
                            'hidden': 'hidden' in base.lower(),
                            'weight': 20
                        })
            q['testCases'] = tc_list

    return questions


@coding_bp.route('/api/import_preview', methods=['POST'])
def api_import_preview():
    """Uploads and previews coding questions from JSON, CSV, DOCX, or ZIP."""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file was uploaded.'}), 400

    uploaded_file = request.files['file']
    filename = uploaded_file.filename.lower()
    content = uploaded_file.read()

    try:
        if filename.endswith('.json'):
            raw_questions = parse_coding_json(content)
        elif filename.endswith('.csv'):
            raw_questions = parse_coding_csv(content)
        elif filename.endswith('.docx'):
            raw_questions = parse_coding_docx(content)
        elif filename.endswith('.zip'):
            raw_questions = parse_coding_zip(content)
        else:
            return jsonify({'success': False, 'error': 'Unsupported file format. Please upload .json, .csv, .docx, or .zip.'}), 400

        if not raw_questions:
            return jsonify({'success': False, 'error': 'No coding questions found in the uploaded file.'}), 400

        preview_list = []
        valid_count = 0
        invalid_count = 0

        for idx, item in enumerate(raw_questions, 1):
            val_res = CodingQuestionValidationService.validate_question(item, index=idx)
            item_data = val_res['data']
            item_data['isValid'] = val_res['is_valid']
            item_data['errors'] = val_res['errors']
            item_data['fieldErrors'] = val_res['field_errors']
            preview_list.append(item_data)
            if val_res['is_valid']:
                valid_count += 1
            else:
                invalid_count += 1

        return jsonify({
            'success': True,
            'filename': uploaded_file.filename,
            'total': len(preview_list),
            'valid_count': valid_count,
            'invalid_count': invalid_count,
            'questions': preview_list
        })

    except Exception as e:
        return jsonify({'success': False, 'error': f'Failed to parse file: {str(e)}'}), 500


@coding_bp.route('/api/import_confirm', methods=['POST'])
def api_import_confirm():
    """Commits validated questions into the database."""
    payload = request.json or {}
    questions_list = payload.get('questions', [])
    quiz_id = payload.get('quiz_id')

    if not questions_list:
        return jsonify({'success': False, 'error': 'No questions provided for import.'}), 400

    saved_count = 0
    errors = []

    for idx, q_dict in enumerate(questions_list, 1):
        val = CodingQuestionValidationService.validate_question(q_dict, index=idx)
        if val['is_valid']:
            try:
                save_coding_question_to_db(val['data'], quiz_id=quiz_id)
                saved_count += 1
            except Exception as e:
                errors.append(f"Question {idx}: Database error: {str(e)}")
        else:
            errors.extend(val['errors'])

    return jsonify({
        'success': saved_count > 0,
        'saved_count': saved_count,
        'failed_count': len(questions_list) - saved_count,
        'errors': errors
    })


# --- SAMPLE TEMPLATES DOWNLOAD ---

@coding_bp.route('/api/sample/<fmt>', methods=['GET'])
def api_download_sample(fmt):
    """Download sample coding question templates."""
    fmt = fmt.lower()
    samples_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'samples')
    os.makedirs(samples_dir, exist_ok=True)

    if fmt == 'json':
        sample_path = os.path.join(samples_dir, 'sample_coding.json')
        if not os.path.exists(sample_path):
            sample_data = {
                "assessmentId": "assessment_001",
                "questions": [
                    {
                        "id": "code_001",
                        "type": "coding",
                        "title": "Add Two Numbers",
                        "difficulty": "Easy",
                        "category": "Basic Programming",
                        "tags": ["arithmetic", "input-output"],
                        "problemStatement": "Write a program that reads two integers and prints their sum.",
                        "inputFormat": "Two space-separated integers.",
                        "outputFormat": "Print the sum of the two integers.",
                        "constraints": ["-1000000000 <= a, b <= 1000000000"],
                        "supportedLanguages": ["python", "c", "cpp", "java", "javascript"],
                        "starterCode": DEFAULT_BOILERPLATES,
                        "samples": [
                            {
                                "input": "5 7",
                                "expectedOutput": "12",
                                "explanation": "5 + 7 = 12"
                            }
                        ],
                        "testCases": [
                            {
                                "id": "tc_001",
                                "input": "5 7",
                                "expectedOutput": "12",
                                "hidden": False,
                                "weight": 20
                            },
                            {
                                "id": "tc_002",
                                "input": "10 20",
                                "expectedOutput": "30",
                                "hidden": True,
                                "weight": 40
                            },
                            {
                                "id": "tc_003",
                                "input": "-5 8",
                                "expectedOutput": "3",
                                "hidden": True,
                                "weight": 40
                            }
                        ],
                        "marks": 10,
                        "negativeMarks": 2,
                        "timeLimitMs": 2000,
                        "memoryLimitMb": 256,
                        "evaluationSettings": DEFAULT_EVALUATION_SETTINGS,
                        "status": "draft",
                        "explanation": "The program should read two integers and print their sum."
                    },
                    {
                        "id": "code_002",
                        "type": "coding",
                        "title": "Reverse a String",
                        "difficulty": "Medium",
                        "category": "Strings",
                        "tags": ["string", "two-pointers"],
                        "problemStatement": "Given a string S, output the reverse of the string.",
                        "inputFormat": "A single line containing the string S.",
                        "outputFormat": "Print the reversed string.",
                        "constraints": ["1 <= length(S) <= 10^5"],
                        "supportedLanguages": ["python", "c", "cpp", "java", "javascript"],
                        "starterCode": DEFAULT_BOILERPLATES,
                        "samples": [
                            {
                                "input": "hello",
                                "expectedOutput": "olleh",
                                "explanation": "Reversing 'hello' gives 'olleh'"
                            }
                        ],
                        "testCases": [
                            {
                                "id": "tc_001",
                                "input": "hello",
                                "expectedOutput": "olleh",
                                "hidden": False,
                                "weight": 50
                            },
                            {
                                "id": "tc_002",
                                "input": "racecar",
                                "expectedOutput": "racecar",
                                "hidden": True,
                                "weight": 50
                            }
                        ],
                        "marks": 15,
                        "negativeMarks": 3,
                        "timeLimitMs": 2000,
                        "memoryLimitMb": 256,
                        "evaluationSettings": DEFAULT_EVALUATION_SETTINGS,
                        "status": "published",
                        "explanation": "Reverse the character sequence from end to beginning."
                    }
                ]
            }
            with open(sample_path, 'w', encoding='utf-8') as f:
                json.dump(sample_data, f, indent=2)

        return send_file(sample_path, as_attachment=True, download_name='sample_coding.json', mimetype='application/json')

    elif fmt == 'csv':
        sample_path = os.path.join(samples_dir, 'sample_coding.csv')
        if not os.path.exists(sample_path):
            fieldnames = [
                'id', 'type', 'title', 'difficulty', 'category', 'tags',
                'problemStatement', 'inputFormat', 'outputFormat', 'constraints',
                'supportedLanguages', 'starterCode', 'samples', 'testCases',
                'marks', 'negativeMarks', 'timeLimitMs', 'memoryLimitMb', 'status'
            ]
            rows = [
                {
                    'id': 'code_001',
                    'type': 'coding',
                    'title': 'Add Two Numbers',
                    'difficulty': 'Easy',
                    'category': 'Basic Programming',
                    'tags': 'arithmetic,input-output',
                    'problemStatement': 'Write a program that reads two integers and prints their sum.',
                    'inputFormat': 'Two space-separated integers.',
                    'outputFormat': 'Print the sum of the two integers.',
                    'constraints': json.dumps(["-1000000000 <= a, b <= 1000000000"]),
                    'supportedLanguages': 'python,c,cpp,java,javascript',
                    'starterCode': json.dumps(DEFAULT_BOILERPLATES),
                    'samples': json.dumps([{"input": "5 7", "expectedOutput": "12", "explanation": "5 + 7 = 12"}]),
                    'testCases': json.dumps([
                        {"id": "tc_001", "input": "5 7", "expectedOutput": "12", "hidden": False, "weight": 20},
                        {"id": "tc_002", "input": "10 20", "expectedOutput": "30", "hidden": True, "weight": 40},
                        {"id": "tc_003", "input": "-5 8", "expectedOutput": "3", "hidden": True, "weight": 40}
                    ]),
                    'marks': 10,
                    'negativeMarks': 2,
                    'timeLimitMs': 2000,
                    'memoryLimitMb': 256,
                    'status': 'draft'
                }
            ]
            with open(sample_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

        return send_file(sample_path, as_attachment=True, download_name='sample_coding.csv', mimetype='text/csv')

    elif fmt == 'docx':
        sample_path = os.path.join(samples_dir, 'sample_coding.docx')
        if not os.path.exists(sample_path) and docx:
            doc = docx.Document()
            doc.add_heading('QuizMaster Coding Question Template', level=1)
            p = doc.add_paragraph('Fill in the table below to import coding questions. Each table represents one coding challenge.')

            table = doc.add_table(rows=15, cols=2)
            table.style = 'Table Grid'
            fields = [
                ('Question ID', 'code_001'),
                ('Title', 'Add Two Numbers'),
                ('Difficulty', 'Easy'),
                ('Category', 'Basic Programming'),
                ('Problem Statement', 'Write a program that reads two integers and prints their sum.'),
                ('Input Format', 'Two space-separated integers.'),
                ('Output Format', 'Print the sum of the two integers.'),
                ('Constraints', '-10^9 <= a, b <= 10^9'),
                ('Supported Languages', 'python, c, cpp, java, javascript'),
                ('Starter Code', json.dumps(DEFAULT_BOILERPLATES)),
                ('Sample Input', '5 7'),
                ('Sample Output', '12'),
                ('Test Cases', json.dumps([
                    {"id": "tc_001", "input": "5 7", "expectedOutput": "12", "hidden": False, "weight": 50},
                    {"id": "tc_002", "input": "10 20", "expectedOutput": "30", "hidden": True, "weight": 50}
                ])),
                ('Marks', '10'),
                ('Negative Marks', '2')
            ]
            for i, (k, v) in enumerate(fields):
                table.rows[i].cells[0].text = k
                table.rows[i].cells[1].text = v

            doc.save(sample_path)

        return send_file(sample_path, as_attachment=True, download_name='sample_coding.docx', mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')

    elif fmt == 'zip':
        sample_path = os.path.join(samples_dir, 'sample_coding.zip')
        if not os.path.exists(sample_path):
            json_str = json.dumps({
                "assessmentId": "sample_assessment",
                "questions": [
                    {
                        "id": "code_001",
                        "title": "Add Two Numbers",
                        "difficulty": "Easy",
                        "problemStatement": "Write a program that reads two integers and prints their sum.",
                        "supportedLanguages": ["python", "cpp", "java", "javascript"],
                        "starterCode": DEFAULT_BOILERPLATES,
                        "marks": 10,
                        "negativeMarks": 2,
                        "testCases": [
                            {"id": "tc_001", "input": "5 7", "expectedOutput": "12", "hidden": False, "weight": 50},
                            {"id": "tc_002", "input": "10 20", "expectedOutput": "30", "hidden": True, "weight": 50}
                        ]
                    }
                ]
            }, indent=2)

            with zipfile.ZipFile(sample_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('questions.json', json_str)
                zf.writestr('code_001_tc1.in', '5 7')
                zf.writestr('code_001_tc1.out', '12')
                zf.writestr('code_001_tc2.in', '10 20')
                zf.writestr('code_001_tc2.out', '30')

        return send_file(sample_path, as_attachment=True, download_name='sample_coding.zip', mimetype='application/zip')

    return jsonify({'error': f'Unknown sample format: {fmt}'}), 400


# --- EXPORT (JSON, CSV, DOCX, ZIP) ---

@coding_bp.route('/api/export', methods=['GET'])
def api_export_questions():
    """Export coding questions to JSON, CSV, DOCX, or ZIP."""
    fmt = request.args.get('format', 'json').lower()
    scope = request.args.get('scope', 'all')
    ids_str = request.args.get('ids', '')
    quiz_id = request.args.get('quiz_id')

    conn = get_db_connection()
    with conn.cursor() as cursor:
        if scope == 'selected' and ids_str:
            id_list = [int(x) for x in ids_str.split(',') if x.strip().isdigit()]
            if not id_list:
                id_list = [-1]
            cursor.execute(f"SELECT * FROM Questions WHERE question_id IN ({','.join(['%s']*len(id_list))})", id_list)
        elif scope == 'quiz' and quiz_id:
            cursor.execute("SELECT * FROM Questions WHERE quiz_id=%s AND (question_type='coding' OR module='Coding')", (quiz_id,))
        else:
            cursor.execute("SELECT * FROM Questions WHERE question_type='coding' OR module='Coding' ORDER BY question_id ASC")
        rows = cursor.fetchall()
    conn.close()

    questions = [format_row_to_coding_dict(r) for r in rows]

    if fmt == 'json':
        export_payload = {
            'exportedAt': datetime.now().isoformat(),
            'count': len(questions),
            'questions': questions
        }
        json_bytes = json.dumps(export_payload, indent=2).encode('utf-8')
        return send_file(
            io.BytesIO(json_bytes),
            as_attachment=True,
            download_name=f"coding_questions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mimetype='application/json'
        )

    elif fmt == 'csv':
        output = io.StringIO()
        fieldnames = [
            'id', 'type', 'title', 'difficulty', 'category', 'tags',
            'problemStatement', 'inputFormat', 'outputFormat', 'constraints',
            'supportedLanguages', 'starterCode', 'samples', 'testCases',
            'marks', 'negativeMarks', 'timeLimitMs', 'memoryLimitMb', 'status'
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for q in questions:
            writer.writerow({
                'id': q['id'],
                'type': 'coding',
                'title': q['title'],
                'difficulty': q['difficulty'],
                'category': q['category'],
                'tags': ','.join(q['tags']) if isinstance(q['tags'], list) else str(q['tags']),
                'problemStatement': q['problemStatement'],
                'inputFormat': q['inputFormat'],
                'outputFormat': q['outputFormat'],
                'constraints': json.dumps(q['constraints']),
                'supportedLanguages': ','.join(q['supportedLanguages']),
                'starterCode': json.dumps(q['starterCode']),
                'samples': json.dumps(q['samples']),
                'testCases': json.dumps(q['testCases']),
                'marks': q['marks'],
                'negativeMarks': q['negativeMarks'],
                'timeLimitMs': q['timeLimitMs'],
                'memoryLimitMb': q['memoryLimitMb'],
                'status': q['status']
            })

        csv_bytes = output.getvalue().encode('utf-8')
        return send_file(
            io.BytesIO(csv_bytes),
            as_attachment=True,
            download_name=f"coding_questions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mimetype='text/csv'
        )

    elif fmt == 'docx':
        if not docx:
            return jsonify({'error': 'python-docx is not installed on the server.'}), 500

        doc = docx.Document()
        doc.add_heading('QuizMaster Coding Questions Repository', level=1)
        p = doc.add_paragraph(f"Exported on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Total {len(questions)} Coding Challenges")

        for idx, q in enumerate(questions, 1):
            doc.add_heading(f"Challenge {idx}: {q['title']} [{q['difficulty']}]", level=2)
            table = doc.add_table(rows=14, cols=2)
            table.style = 'Table Grid'
            fields = [
                ('Question ID', q['id']),
                ('Title', q['title']),
                ('Difficulty', q['difficulty']),
                ('Category', q['category']),
                ('Problem Statement', q['problemStatement']),
                ('Input Format', q['inputFormat']),
                ('Output Format', q['outputFormat']),
                ('Constraints', '\n'.join(q['constraints']) if isinstance(q['constraints'], list) else str(q['constraints'])),
                ('Supported Languages', ', '.join(q['supportedLanguages'])),
                ('Starter Code', json.dumps(q['starterCode'])),
                ('Samples', json.dumps(q['samples'])),
                ('Test Cases', json.dumps(q['testCases'])),
                ('Marks', str(q['marks'])),
                ('Negative Marks', str(q['negativeMarks']))
            ]
            for r_idx, (k, v) in enumerate(fields):
                table.rows[r_idx].cells[0].text = k
                table.rows[r_idx].cells[1].text = v

            doc.add_paragraph('')

        docx_io = io.BytesIO()
        doc.save(docx_io)
        docx_io.seek(0)
        return send_file(
            docx_io,
            as_attachment=True,
            download_name=f"coding_questions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx",
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )

    elif fmt == 'zip':
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            json_str = json.dumps({'count': len(questions), 'questions': questions}, indent=2)
            zf.writestr('questions.json', json_str)

            # Write individual testcase files
            for q in questions:
                q_id = q['id']
                for c_idx, tc in enumerate(q.get('testCases', []), 1):
                    zf.writestr(f"{q_id}_tc{c_idx}.in", tc.get('input', ''))
                    zf.writestr(f"{q_id}_tc{c_idx}.out", tc.get('expectedOutput', ''))

        zip_buffer.seek(0)
        return send_file(
            zip_buffer,
            as_attachment=True,
            download_name=f"coding_questions_package_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
            mimetype='application/zip'
        )

    return jsonify({'error': f'Unsupported export format: {fmt}'}), 400
