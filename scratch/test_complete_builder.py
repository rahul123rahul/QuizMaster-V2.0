import sys
import os
import json
sys.path.insert(0, os.path.abspath('.'))
from main import app
from utils import get_db_connection

def test_all():
    print("=== Testing Question Builder and Content Management System ===")
    client = app.test_client()

    with client.session_transaction() as sess:
        sess['role'] = 'Admin'
        sess['user_id'] = 1
        sess['full_name'] = 'System Administrator'

    # 1. Test /admin/content route
    res = client.get('/admin/content')
    assert res.status_code == 200, f"/admin/content returned {res.status_code}"
    assert b"Question Builder" in res.data, "Title not found in /admin/content"
    assert b"Advanced Settings" in res.data, "Advanced Settings not found in /admin/content"
    print("PASS: /admin/content loaded successfully (HTTP 200)")

    # 2. Test /admin/question_builder alias
    res2 = client.get('/admin/question_builder')
    assert res2.status_code == 200
    print("PASS: /admin/question_builder alias loaded successfully (HTTP 200)")

    # 3. Test saving all 14 question types
    all_14_types = [
        {
            "type": "mcq",
            "text": "Which language is known for snake mascot?",
            "meta": {"options": [{"id": "A", "text": "Python", "is_correct": True}, {"id": "B", "text": "Java", "is_correct": False}], "correct_id": "A"}
        },
        {
            "type": "single_choice",
            "text": "What is 2 + 2 in base 10?",
            "meta": {"options": [{"id": "A", "text": "4", "is_correct": True}, {"id": "B", "text": "5", "is_correct": False}], "correct_id": "A"}
        },
        {
            "type": "multiple_select",
            "text": "Select all prime numbers below 10:",
            "meta": {"options": [{"id": "A", "text": "2", "is_correct": True}, {"id": "B", "text": "3", "is_correct": True}, {"id": "C", "text": "4", "is_correct": False}]}
        },
        {
            "type": "true_false",
            "text": "Light travels faster than sound in a vacuum.",
            "meta": {"correct_value": "True"}
        },
        {
            "type": "fill_blank",
            "text": "The first letter of the English alphabet is ____.",
            "meta": {"acceptable_answers": ["A"], "case_sensitive": True, "trim_whitespace": True}
        },
        {
            "type": "short_answer",
            "text": "Define HTTP in one word or abbreviation:",
            "meta": {"acceptable_answers": ["protocol"], "keywords": ["protocol", "hypertext"]}
        },
        {
            "type": "long_answer",
            "text": "Discuss the advantages of microservices architecture.",
            "meta": {"min_words": 50, "max_words": 300, "rubric": "Scalability, Fault isolation"}
        },
        {
            "type": "matching",
            "text": "Match capitals to countries:",
            "meta": {"pairs": [{"premise": "France", "target": "Paris"}, {"premise": "Japan", "target": "Tokyo"}]}
        },
        {
            "type": "ordering",
            "text": "Order the steps of baking:",
            "meta": {"items": ["Mix ingredients", "Preheat oven", "Bake"]}
        },
        {
            "type": "numerical",
            "text": "What is the speed of sound in dry air at 20°C in m/s?",
            "meta": {"correct_value": 343.0, "tolerance": 2.0, "unit": "m/s"}
        },
        {
            "type": "dropdown",
            "text": "Select the correct paradigm: Python is an [blank_1] language.",
            "meta": {"choices": ["OOP", "Functional"], "correct_choice": "OOP"}
        },
        {
            "type": "image_based",
            "text": "Identify the logic gate shown in the image.",
            "meta": {"image_url": "/static/uploads/gate.png", "options": [{"id": "A", "text": "AND Gate", "is_correct": True}], "correct_id": "A"}
        },
        {
            "type": "audio_based",
            "text": "Listen to the pronunciation and choose the word:",
            "meta": {"audio_url": "/static/uploads/word.ogg", "options": [{"id": "A", "text": "Epitome", "is_correct": True}], "correct_id": "A"}
        },
        {
            "type": "passage_based",
            "text": "Read the passage about AI safety and answer questions.",
            "meta": {"passage_text": "AI systems require robustness and alignment...", "subquestions": [{"title": "What is required?", "options": [{"text": "Alignment", "is_correct": True}]}]}
        }
    ]

    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute('SELECT quiz_id FROM Quizzes LIMIT 1')
        row = cur.fetchone()
        valid_quiz_id = row['quiz_id'] if row else 3
    conn.close()

    saved_ids = []
    for item in all_14_types:
        payload = {
            "quiz_id": valid_quiz_id,
            "question_type": item["type"],
            "question_text": f"[Automated Test] {item['text']}",
            "marks": 2,
            "negative_marks": 0.5,
            "difficulty": "Medium",
            "status": "Published",
            "subject": "Testing Subject",
            "explanation": "Test explanation.",
            "meta": item["meta"]
        }
        res_save = client.post('/admin/question_bank/save', data=json.dumps(payload), content_type='application/json')
        assert res_save.status_code == 200, f"Failed saving {item['type']}: {res_save.data}"
        json_data = json.loads(res_save.data)
        assert json_data['success'] is True, f"Response indicated failure for {item['type']}"
        print(f"PASS: Saved {item['type']} question successfully.")

    # 4. Test Advance Settings GET & POST
    adv_payload = {
        "enable_negative_marking": True,
        "negative_carry_allowed": True,
        "radio_incorrect_deduct": 0.33,
        "checkbox_incorrect_deduct": 0.66,
        "fill_blank_case_sensitive": True,
        "fill_blank_trim_whitespace": True,
        "fill_blank_ignore_punctuation": True
    }
    res_adv_post = client.post('/admin/api/advance_settings', data=json.dumps(adv_payload), content_type='application/json')
    assert res_adv_post.status_code == 200
    res_adv_get = client.get('/admin/api/advance_settings')
    adv_data = json.loads(res_adv_get.data)
    assert adv_data['settings']['radio_incorrect_deduct'] == 0.33
    assert adv_data['settings']['fill_blank_case_sensitive'] is True
    print("PASS: Advance Settings GET and POST persisted successfully.")

    # 5. Test Export API
    res_exp_json = client.get('/admin/api/questions/export?format=json')
    assert res_exp_json.status_code == 200
    assert res_exp_json.content_type == 'application/json'

    res_exp_csv = client.get('/admin/api/questions/export?format=csv')
    assert res_exp_csv.status_code == 200
    assert 'text/csv' in res_exp_csv.content_type
    print("PASS: Questions Export (JSON and CSV) verified.")

    print("\nALL AUTOMATED TESTS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    test_all()
