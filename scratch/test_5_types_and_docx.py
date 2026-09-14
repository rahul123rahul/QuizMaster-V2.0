import sys
import os
import json
import io
import docx
sys.path.insert(0, os.path.abspath('.'))
from main import app
from utils import get_db_connection

def test_all():
    print("=== Testing 5-Type Question Builder, DOCX/JSON/CSV Importer & Bulk Creator ===")
    client = app.test_client()

    with client.session_transaction() as sess:
        sess['role'] = 'Admin'
        sess['user_id'] = 1
        sess['full_name'] = 'System Administrator'

    # Get valid quiz_id
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute('SELECT quiz_id FROM Quizzes LIMIT 1')
        row = cur.fetchone()
        valid_quiz_id = row['quiz_id'] if row else 3
    conn.close()

    # 1. Test /admin/content page load
    res = client.get('/admin/content')
    assert res.status_code == 200, f"/admin/content returned {res.status_code}"
    assert b"Question Builder" in res.data
    print("PASS: /admin/content loaded successfully (HTTP 200)")

    # 2. Test Single Question Save for the 5 types
    test_5_types = [
        {
            "question_type": "mscq_single",
            "question_text": "[Automated Test] Which language is used to structure web pages?",
            "options": [{"id": "A", "text": "HTML"}, {"id": "B", "text": "CSS"}, {"id": "C", "text": "Python"}, {"id": "D", "text": "SQL"}],
            "correctAnswer": "A",
            "marks": 1,
            "negative_marks": 0.25,
            "explanation": "HTML is markup language."
        },
        {
            "question_type": "mscq_multiple",
            "question_text": "[Automated Test] Which of the following are programming languages?",
            "options": [{"id": "A", "text": "Java"}, {"id": "B", "text": "Python"}, {"id": "C", "text": "HTML"}, {"id": "D", "text": "C++"}],
            "correctAnswer": "A, B, D",
            "marks": 2,
            "negative_marks": 0.5,
            "explanation": "Java, Python, C++ are programming languages."
        },
        {
            "question_type": "mscq_select",
            "question_text": "[Automated Test] Select the correct database language.",
            "options": [{"id": "A", "text": "HTML"}, {"id": "B", "text": "CSS"}, {"id": "C", "text": "SQL"}, {"id": "D", "text": "Python"}],
            "correctAnswer": "C",
            "marks": 1,
            "negative_marks": 0.25,
            "explanation": "SQL is database language."
        },
        {
            "question_type": "fill_blank",
            "question_text": "[Automated Test] The first letter of the English alphabet is ____.",
            "acceptedAnswers": ["A"],
            "correctAnswer": "A",
            "caseSensitive": True,
            "marks": 1,
            "negative_marks": 0.25,
            "explanation": "A is the first letter."
        },
        {
            "question_type": "true_false",
            "question_text": "[Automated Test] HTML is a programming language.",
            "correctAnswer": "False",
            "marks": 1,
            "negative_marks": 0.25,
            "explanation": "HTML is a markup language."
        }
    ]

    for q in test_5_types:
        payload = {
            "quiz_id": valid_quiz_id,
            "question_type": q["question_type"],
            "question_text": q["question_text"],
            "marks": q["marks"],
            "negative_marks": q["negative_marks"],
            "explanation": q["explanation"],
            "subject": "Automated Testing",
            "meta": q
        }
        res_save = client.post('/admin/question_bank/save', data=json.dumps(payload), content_type='application/json')
        assert res_save.status_code == 200, f"Failed saving {q['question_type']}: {res_save.data}"
        json_res = json.loads(res_save.data)
        assert json_res['success'] is True
        print(f"PASS: Saved single question of type '{q['question_type']}'.")

    # 3. Test Bulk Question Authoring Creation API
    bulk_payload = {
        "quiz_id": valid_quiz_id,
        "questions": [
            {
                "question_type": "mscq_single",
                "question_text": "[Automated Test] Bulk Single Choice 1",
                "options": [{"id": "A", "text": "Option 1"}, {"id": "B", "text": "Option 2"}],
                "correct_answer": "A",
                "marks": 1,
                "negative_marks": 0.25,
                "explanation": "Bulk Explanation 1"
            },
            {
                "question_type": "fill_blank",
                "question_text": "[Automated Test] Bulk Blank: Sun rises in the ____.",
                "correct_answer": "East",
                "case_sensitive": False,
                "marks": 1,
                "negative_marks": 0.25,
                "explanation": "Sun rises in East"
            }
        ]
    }
    res_bulk = client.post('/admin/api/questions/bulk_create', data=json.dumps(bulk_payload), content_type='application/json')
    assert res_bulk.status_code == 200, f"Bulk create failed: {res_bulk.data}"
    bulk_res = json.loads(res_bulk.data)
    assert bulk_res['success'] is True
    assert bulk_res['count'] == 2
    print(f"PASS: Bulk create saved {bulk_res['count']} questions successfully.")

    # 4. Test DOCX Import Preview
    with open('static/samples/sample_questions.docx', 'rb') as f:
        docx_bytes = f.read()
    data_docx = {
        'file': (io.BytesIO(docx_bytes), 'sample_questions.docx')
    }
    res_docx_prev = client.post('/admin/api/questions/import_preview', data=data_docx, content_type='multipart/form-data')
    assert res_docx_prev.status_code == 200, f"DOCX preview failed: {res_docx_prev.data}"
    docx_res = json.loads(res_docx_prev.data)
    assert docx_res['success'] is True
    assert docx_res['summary']['total'] == 5
    assert docx_res['summary']['valid'] == 5
    print(f"PASS: DOCX Parser accurately parsed {docx_res['summary']['valid']}/5 valid questions.")

    # 5. Test JSON Import Preview
    with open('static/samples/sample_questions.json', 'rb') as f:
        json_bytes = f.read()
    data_json = {
        'file': (io.BytesIO(json_bytes), 'sample_questions.json')
    }
    res_json_prev = client.post('/admin/api/questions/import_preview', data=data_json, content_type='multipart/form-data')
    assert res_json_prev.status_code == 200
    json_p_res = json.loads(res_json_prev.data)
    assert json_p_res['summary']['valid'] == 5
    print(f"PASS: JSON Parser parsed 5/5 valid questions.")

    # 6. Test CSV Import Preview
    with open('static/samples/sample_questions.csv', 'rb') as f:
        csv_bytes = f.read()
    data_csv = {
        'file': (io.BytesIO(csv_bytes), 'sample_questions.csv')
    }
    res_csv_prev = client.post('/admin/api/questions/import_preview', data=data_csv, content_type='multipart/form-data')
    assert res_csv_prev.status_code == 200
    csv_p_res = json.loads(res_csv_prev.data)
    assert csv_p_res['summary']['valid'] == 5
    print(f"PASS: CSV Parser parsed 5/5 valid questions.")

    # 7. Test Download Sample Endpoints
    for fmt in ['json', 'csv', 'docx']:
        res_sample = client.get(f'/admin/api/questions/sample/{fmt}')
        assert res_sample.status_code == 200, f"Sample download for {fmt} failed"
        assert len(res_sample.data) > 0
        print(f"PASS: Download Sample for {fmt.upper()} works ({len(res_sample.data)} bytes).")

    # 8. Test Export Endpoints (Word DOCX, JSON, CSV)
    res_exp_docx = client.get('/admin/api/questions/export?format=docx')
    assert res_exp_docx.status_code == 200, f"DOCX export failed: {res_exp_docx.status_code}"
    assert len(res_exp_docx.data) > 0
    # Verify docx parses cleanly
    test_exported_doc = docx.Document(io.BytesIO(res_exp_docx.data))
    assert len(test_exported_doc.paragraphs) > 0
    print(f"PASS: Export for Word (.docx) verified ({len(res_exp_docx.data)} bytes, valid Document structure).")

    res_exp_json = client.get('/admin/api/questions/export?format=json')
    assert res_exp_json.status_code == 200
    res_exp_csv = client.get('/admin/api/questions/export?format=csv')
    assert res_exp_csv.status_code == 200
    print("PASS: Export for JSON and CSV verified.")

    # 9. Test Question Repository page (/admin/repository)
    res_repo = client.get('/admin/repository')
    assert res_repo.status_code == 200, f"Repository page failed: {res_repo.status_code}"
    assert b"Question Repository" in res_repo.data
    assert b"id=\"questionsTable\"" in res_repo.data
    print("PASS: Dedicated Question Repository page (/admin/repository) loaded with questions table.")

    # 10. Verify /admin/content does NOT show the questionsTable
    res_content = client.get('/admin/content')
    assert res_content.status_code == 200
    assert b"id=\"questionsTable\"" not in res_content.data
    assert b"Ready to view or manage questions?" in res_content.data
    print("PASS: /admin/content does NOT show questions table below content editor as requested.")

    # Cleanup automated test questions
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute('DELETE FROM Questions WHERE question_text LIKE %s', ('%[Automated Test]%',))
        conn.commit()
    conn.close()
    print("PASS: Cleaned up automated test questions from DB.")

    print("\nALL 5-TYPE, BULK CREATION & DOCX/JSON/CSV TESTS PASSED!")

if __name__ == '__main__':
    test_all()
