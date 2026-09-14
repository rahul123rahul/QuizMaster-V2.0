import os
import sys
import json

sys.path.insert(0, r'c:\Users\rahul\OneDrive\Documents\GitHub\Quiz-master-with-Ai')

from database import get_db_connection
from main import app

def test_api_and_scoring():
    print("--- Testing API Save Answer & Submit Quiz Scoring ---")
    client = app.test_client()
    
    conn = get_db_connection()
    cur = conn.cursor()

    # 1. Create a temporary quiz
    cur.execute("INSERT INTO Quizzes (title, duration_minutes) VALUES ('Test Multi-Type Scoring Quiz', 20)")
    quiz_id = cur.lastrowid

    # 2. Add 5 distinct questions + 1 coding question
    # Q1: Single Choice (Marks: 2, Neg: 0.5)
    cur.execute("""
        INSERT INTO Questions (quiz_id, question_type, question_text, option_a, option_b, option_c, option_d, correct_option, marks, negative_marks, metadata_json)
        VALUES (%s, 'mscq_single', 'Single choice test', 'Apple', 'Banana', 'Orange', 'Mango', 'A', 2, 0.5, %s)
    """, (quiz_id, json.dumps({'options': [{'id': 'A', 'text': 'Apple'}, {'id': 'B', 'text': 'Banana'}]})))
    q1_id = cur.lastrowid

    # Q2: Multiple Choice (Marks: 3, Neg: 1.0)
    cur.execute("""
        INSERT INTO Questions (quiz_id, question_type, question_text, option_a, option_b, option_c, option_d, correct_option, marks, negative_marks, metadata_json)
        VALUES (%s, 'mscq_multiple', 'Multiple choice test', 'Red', 'Blue', 'Green', 'Dog', 'A, B', 3, 1.0, %s)
    """, (quiz_id, json.dumps({'options': [{'id': 'A', 'text': 'Red'}, {'id': 'B', 'text': 'Blue'}, {'id': 'C', 'text': 'Green'}]})))
    q2_id = cur.lastrowid

    # Q3: Select Dropdown (Marks: 1, Neg: 0)
    cur.execute("""
        INSERT INTO Questions (quiz_id, question_type, question_text, option_a, option_b, correct_option, marks, negative_marks, metadata_json)
        VALUES (%s, 'mscq_select', 'Dropdown test', 'True', 'False', 'A', 1, 0, %s)
    """, (quiz_id, json.dumps({'options': [{'id': 'A', 'text': 'True'}, {'id': 'B', 'text': 'False'}]})))
    q3_id = cur.lastrowid

    # Q4: Fill in Blanks (Marks: 2, Neg: 0.5, case-sensitive)
    cur.execute("""
        INSERT INTO Questions (quiz_id, question_type, question_text, correct_option, marks, negative_marks, metadata_json)
        VALUES (%s, 'fill_blank', 'Blank test', 'Python', 2, 0.5, %s)
    """, (quiz_id, json.dumps({'acceptedAnswers': ['Python'], 'caseSensitive': True})))
    q4_id = cur.lastrowid

    # Q5: True/False (Marks: 1, Neg: 0.25)
    cur.execute("""
        INSERT INTO Questions (quiz_id, question_type, question_text, correct_option, marks, negative_marks, metadata_json)
        VALUES (%s, 'true_false', 'TF test', 'False', 1, 0.25, %s)
    """, (quiz_id, json.dumps({'correctAnswer': 'False'})))
    q5_id = cur.lastrowid

    # Create Quiz Attempt
    cur.execute("INSERT INTO Quiz_Attempts (user_id, quiz_id, total_score, status) VALUES (1, %s, 0, 'In-Progress')", (quiz_id,))
    attempt_id = cur.lastrowid
    conn.commit()

    try:
        # Save answers:
        # Q1: Correct -> 'A' (+2)
        r = client.post('/api/save_answer', json={'attempt_id': attempt_id, 'question_id': q1_id, 'option': 'A'})
        assert r.status_code == 200

        # Q2: Correct multi-choice -> 'A, B' (+3)
        r = client.post('/api/save_answer', json={'attempt_id': attempt_id, 'question_id': q2_id, 'option': 'A, B'})
        assert r.status_code == 200

        # Q3: Wrong dropdown -> 'B' (Incorrect, neg: 0) -> 0
        r = client.post('/api/save_answer', json={'attempt_id': attempt_id, 'question_id': q3_id, 'option': 'B'})
        assert r.status_code == 200

        # Q4: Wrong case -> 'python' when case-sensitive is True -> incorrect (Neg: 0.5) -> -0.5
        r = client.post('/api/save_answer', json={'attempt_id': attempt_id, 'question_id': q4_id, 'option': 'python'})
        assert r.status_code == 200

        # Q5: Correct TF -> 'False' (+1)
        r = client.post('/api/save_answer', json={'attempt_id': attempt_id, 'question_id': q5_id, 'option': 'False'})
        assert r.status_code == 200

        # Submit Quiz
        res = client.post('/api/submit_quiz', json={'attempt_id': attempt_id})
        data = res.get_json()
        print("Submit response:", data)

        # Expected score:
        # Q1: +2
        # Q2: +3
        # Q3: 0
        # Q4: -0.5
        # Q5: +1
        # Total = 2 + 3 + 0 - 0.5 + 1 = 5.5
        assert data['score'] == 5.5, f"Expected score 5.5, got {data['score']}"
        print(f"[PASS] Successfully scored 5 question types with negative marking: {data['score']} / {data['total']}")

    finally:
        # Cleanup
        cur.execute("DELETE FROM Quiz_Responses WHERE attempt_id=%s", (attempt_id,))
        cur.execute("DELETE FROM Quiz_Attempts WHERE attempt_id=%s", (attempt_id,))
        cur.execute("DELETE FROM Questions WHERE quiz_id=%s", (quiz_id,))
        cur.execute("DELETE FROM Quizzes WHERE quiz_id=%s", (quiz_id,))
        conn.commit()
        conn.close()

if __name__ == '__main__':
    test_api_and_scoring()
