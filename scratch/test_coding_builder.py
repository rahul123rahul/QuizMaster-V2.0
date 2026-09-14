import os
import sys
import json
import io
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from database import get_db_connection
from routes.coding import CodingQuestionValidationService, CodeEvaluationService

class TestCodingBuilder(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config['TESTING'] = True

    def test_01_validation_service(self):
        print("\n--- Testing CodingQuestionValidationService ---")
        # Valid question
        valid_q = {
            'title': 'Sum of Two Numbers',
            'problemStatement': 'Given two integers, print their sum.',
            'difficulty': 'Easy',
            'supportedLanguages': ['python', 'cpp'],
            'marks': 10,
            'negativeMarks': 2,
            'testCases': [
                {'input': '1 2', 'expectedOutput': '3', 'weight': 50},
                {'input': '10 20', 'expectedOutput': '30', 'weight': 50}
            ]
        }
        res = CodingQuestionValidationService.validate_question(valid_q)
        self.assertTrue(res['is_valid'])
        self.assertEqual(res['data']['difficulty'], 'Easy')
        self.assertEqual(len(res['data']['testCases']), 2)
        print("Valid question test: PASSED")

        # Invalid question (missing title and problemStatement, invalid language)
        invalid_q = {
            'title': '',
            'problemStatement': '',
            'difficulty': 'expert', # Should normalize to Easy or flag
            'supportedLanguages': ['ruby', 'rust'],
            'marks': -5
        }
        res_inv = CodingQuestionValidationService.validate_question(invalid_q)
        self.assertFalse(res_inv['is_valid'])
        self.assertIn('title', res_inv['field_errors'])
        self.assertIn('problemStatement', res_inv['field_errors'])
        self.assertIn('supportedLanguages', res_inv['field_errors'])
        self.assertIn('marks', res_inv['field_errors'])
        print("Invalid question validation test: PASSED (caught 4 field errors)")

    def test_02_evaluation_service(self):
        print("\n--- Testing CodeEvaluationService ---")
        code = "a, b = map(int, input().split())\nprint(a + b)"
        test_cases = [
            {'id': 'tc_1', 'input': '4 5', 'expectedOutput': '9', 'hidden': False, 'weight': 50},
            {'id': 'tc_2', 'input': '100 200', 'expectedOutput': '300', 'hidden': True, 'weight': 50}
        ]
        res = CodeEvaluationService.run_tests(code, 'python', test_cases)
        self.assertEqual(res['overallStatus'], 'Accepted')
        self.assertEqual(res['passedCount'], 2)
        self.assertEqual(res['scorePercentage'], 100.0)
        print("CodeEvaluationService execution test: PASSED (Accepted)")

        # Wrong code
        wrong_code = "print(0)"
        res_wrong = CodeEvaluationService.run_tests(wrong_code, 'python', test_cases)
        self.assertEqual(res_wrong['overallStatus'], 'Wrong Answer')
        self.assertEqual(res_wrong['passedCount'], 0)
        print("CodeEvaluationService wrong answer test: PASSED (Wrong Answer)")

    def test_03_crud_endpoints(self):
        print("\n--- Testing Coding Question CRUD Endpoints ---")
        # 1. Create Question
        payload = {
            'id': 'test_code_001',
            'title': 'Test Add Two Numbers',
            'problemStatement': 'Compute the sum of A and B.',
            'difficulty': 'Medium',
            'category': 'Algorithms',
            'tags': ['math', 'easy'],
            'marks': 10,
            'negativeMarks': 2,
            'timeLimitMs': 2000,
            'memoryLimitMb': 256,
            'status': 'published',
            'supportedLanguages': ['python', 'cpp', 'java'],
            'testCases': [
                {'id': 'tc_1', 'input': '3 4', 'expectedOutput': '7', 'weight': 100}
            ]
        }
        r = self.client.post('/admin/coding/save', json=payload)
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data['success'])
        q_id = data['question_id']
        print(f"Created coding question ID: {q_id}")

        # 2. Get Question
        r_get = self.client.get(f'/admin/coding/api/get/{q_id}')
        self.assertEqual(r_get.status_code, 200)
        q_obj = r_get.get_json()['question']
        self.assertEqual(q_obj['title'], 'Test Add Two Numbers')
        self.assertEqual(q_obj['difficulty'], 'Medium')
        self.assertEqual(q_obj['negativeMarks'], 2.0)
        print("Retrieved coding question: PASSED")

        # 3. Duplicate Question
        r_dup = self.client.post(f'/admin/coding/duplicate/{q_id}')
        self.assertEqual(r_dup.status_code, 200)
        dup_id = r_dup.get_json()['new_question_id']
        print(f"Duplicated coding question ID: {dup_id}")

        # 4. Toggle status
        r_stat = self.client.post(f'/admin/coding/status/{q_id}')
        self.assertEqual(r_stat.status_code, 200)
        self.assertEqual(r_stat.get_json()['new_status'], 'draft')
        print("Toggled status: PASSED (now draft)")

        # 5. Delete both test questions
        r_del1 = self.client.post(f'/admin/coding/delete/{q_id}')
        r_del2 = self.client.post(f'/admin/coding/delete/{dup_id}')
        self.assertTrue(r_del1.get_json()['success'])
        self.assertTrue(r_del2.get_json()['success'])
        print("Deleted test questions: PASSED")

    def test_04_bulk_create(self):
        print("\n--- Testing Bulk Create Endpoint ---")
        bulk_payload = {
            'questions': [
                {
                    'title': 'Bulk Question 1',
                    'difficulty': 'Easy',
                    'problemStatement': 'Print 1 to N.',
                    'marks': 10,
                    'supportedLanguages': ['python'],
                    'testCases': [{'input': '5', 'expectedOutput': '1 2 3 4 5', 'weight': 100}]
                },
                {
                    'title': 'Bulk Question 2',
                    'difficulty': 'Difficult',
                    'problemStatement': 'Find shortest path in graph.',
                    'marks': 25,
                    'negativeMarks': 5,
                    'supportedLanguages': ['cpp', 'java'],
                    'testCases': [{'input': '4 4', 'expectedOutput': '12', 'weight': 100}]
                }
            ]
        }
        r = self.client.post('/admin/coding/api/bulk_create', json=bulk_payload)
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertTrue(d['success'])
        self.assertEqual(len(d['created_ids']), 2)
        print(f"Bulk created {len(d['created_ids'])} questions: PASSED")

        # Cleanup
        for cid in d['created_ids']:
            self.client.post(f'/admin/coding/delete/{cid}')

    def test_05_sample_downloads_and_export(self):
        print("\n--- Testing Sample Downloads and Export ---")
        for fmt in ['json', 'csv', 'docx', 'zip']:
            r = self.client.get(f'/admin/coding/api/sample/{fmt}')
            self.assertEqual(r.status_code, 200)
            self.assertGreater(len(r.data), 50)
            print(f"Sample download [{fmt}]: PASSED ({len(r.data)} bytes)")

        # Test Export
        for fmt in ['json', 'csv', 'docx', 'zip']:
            r_exp = self.client.get(f'/admin/coding/api/export?format={fmt}&scope=all')
            self.assertEqual(r_exp.status_code, 200)
            self.assertGreater(len(r_exp.data), 50)
            print(f"Export [{fmt}]: PASSED ({len(r_exp.data)} bytes)")

    def test_06_import_preview(self):
        print("\n--- Testing Import Preview (JSON) ---")
        sample_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'samples', 'sample_coding.json')
        with open(sample_path, 'rb') as f:
            data = {'file': (io.BytesIO(f.read()), 'sample_coding.json')}
            r = self.client.post('/admin/coding/api/import_preview', data=data, content_type='multipart/form-data')
            self.assertEqual(r.status_code, 200)
            d = r.get_json()
            self.assertTrue(d['success'])
            self.assertEqual(d['total'], 2)
            self.assertEqual(d['valid_count'], 2)
            self.assertEqual(d['invalid_count'], 0)
            print("Import preview test: PASSED (2 valid questions detected)")

if __name__ == '__main__':
    unittest.main()
