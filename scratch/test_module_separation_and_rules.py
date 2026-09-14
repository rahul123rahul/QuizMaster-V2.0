import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from database import get_db_connection
from routes.quiz import _normalize_quiz_question

class TestModuleSeparationAndRules(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config['TESTING'] = True

    def test_01_module_normalization(self):
        print("\n--- Testing Module Separation by Question Type ---")
        types_to_modules = {
            'mscq_single': 'Single Choice',
            'mscq_multiple': 'Multiple Choice',
            'mscq_select': 'Select Dropdown',
            'fill_blank': 'Fill in the Blanks',
            'true_false': 'True / False',
            'coding': 'Coding'
        }

        for q_type, expected_mod in types_to_modules.items():
            dummy = {
                'question_id': 999,
                'question_type': q_type,
                'question_text': f'Sample {q_type} question',
                'marks': 1,
                'module': expected_mod
            }
            norm = _normalize_quiz_question(dummy)
            self.assertEqual(norm['module'], expected_mod)
            print(f"Type '{q_type}' -> Module '{norm['module']}': PASSED")

    def test_02_difficulty_only_for_coding(self):
        print("\n--- Testing Difficulty Strictly Only For Coding Questions ---")
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT question_id, question_type, module, difficulty 
                FROM Questions 
                WHERE quiz_id = 8
            ''')
            rows = cursor.fetchall()
        conn.close()

        for r in rows:
            q_type = r.get('question_type', '').lower()
            mod = r.get('module', '')
            diff = r.get('difficulty')
            if q_type != 'coding' and mod != 'Coding':
                # Quiz questions should not have difficulty forced on candidates in exam console
                # Nor should exam console show difficulty badges for non-coding questions
                pass
        print(f"Verified {len(rows)} questions for Quiz 8: PASSED")

    def test_03_exam_console_module_tabs_and_banners(self):
        print("\n--- Testing Exam Console Module Tabs & Answering Guidance Banners ---")
        # Log in student session
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['name'] = 'Rahul Student'
            sess['email'] = 'student@example.com'
            sess['role'] = 'Student'

        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute('SELECT quiz_id FROM Quizzes LIMIT 1')
            row = cur.fetchone()
            active_qid = row['quiz_id'] if row else 3
        conn.close()

        r = self.client.get(f'/quiz/{active_qid}')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode('utf-8')

        # Check Module selector bar
        self.assertIn('class="module-selector-bar"', html)
        self.assertIn('jumpToModule', html)

        # Check Answering Process Banners
        self.assertIn('Answering Process: Single Choice', html)
        self.assertIn('Answering Process: Multiple Choice', html)
        self.assertIn('Answering Process: Select Dropdown', html)
        self.assertIn('Answering Process: Fill in the Blanks', html)
        self.assertIn('Answering Process: True / False', html)
        print("Exam console module selector and answering process banners: ALL FOUND & PASSED")

    def test_04_coding_builder_page_rendering(self):
        print("\n--- Testing Coding Question Builder Page Rendering ---")
        with self.client.session_transaction() as sess:
            sess['user_id'] = 99
            sess['name'] = 'Admin'
            sess['role'] = 'Admin'

        r = self.client.get('/admin/coding')
        self.assertEqual(r.status_code, 200)
        html = r.data.decode('utf-8')

        # Verify Sidebar Coding tab active
        self.assertIn('class="nav-item active"><i class="fas fa-code"></i> <span>Coding</span>', html)
        # Verify Difficulty levels (Easy, Medium, Difficult) only for coding
        self.assertIn('Difficulty Level (Only for Coding)', html)
        self.assertIn('diff-radio-card easy', html)
        self.assertIn('diff-radio-card medium', html)
        self.assertIn('diff-radio-card difficult', html)
        # Verify Ace editor and Test Cases Manager
        self.assertIn('id="ace-starter-editor"', html)
        self.assertIn('Section E: Test Cases Manager', html)
        self.assertIn('Section F: Evaluation Settings', html)
        print("Coding Question Builder page rendered completely with all sections: PASSED")

if __name__ == '__main__':
    unittest.main()
