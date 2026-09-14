import os
import sys
import json

# Ensure workspace root is in path
sys.path.insert(0, r'c:\Users\rahul\OneDrive\Documents\GitHub\Quiz-master-with-Ai')

from main import app
from routes.quiz import _normalize_quiz_question

def test_normalization():
    print("--- 1. Testing Question Normalization ---")
    
    # 1. Single Choice
    q_single = {
        'question_id': 1,
        'question_type': 'mscq_single',
        'question_text': 'What is Python?',
        'option_a': 'Language', 'option_b': 'Snake', 'option_c': 'Car', 'option_d': 'Food',
        'correct_option': 'A',
        'marks': 1, 'negative_marks': 0.25,
        'metadata_json': json.dumps({'options': [{'id': 'A', 'text': 'Language'}, {'id': 'B', 'text': 'Snake'}]})
    }
    norm_single = _normalize_quiz_question(dict(q_single))
    assert norm_single['is_coding'] is False, "Single choice shouldn't be coding"
    assert norm_single['question_type_norm'] == 'mscq_single'
    print("[PASS] Single Choice Normalized")

    # 2. Multiple Choice
    q_multi = {
        'question_id': 2,
        'question_type': 'mscq_multiple',
        'question_text': 'Select programming languages',
        'option_a': 'Python', 'option_b': 'Java', 'option_c': 'HTML', 'option_d': 'C++',
        'correct_option': 'A, B, D',
        'marks': 2, 'negative_marks': 0.5,
        'metadata_json': json.dumps({'options': [{'id': 'A', 'text': 'Python'}, {'id': 'B', 'text': 'Java'}, {'id': 'C', 'text': 'HTML'}, {'id': 'D', 'text': 'C++'}]})
    }
    norm_multi = _normalize_quiz_question(dict(q_multi))
    assert norm_multi['is_coding'] is False, "Multiple choice shouldn't be coding"
    assert norm_multi['question_type_norm'] == 'mscq_multiple'
    print("[PASS] Multiple Choice Normalized")

    # 3. Select Dropdown
    q_dropdown = {
        'question_id': 3,
        'question_type': 'mscq_select',
        'question_text': 'Select query language',
        'option_a': 'SQL', 'option_b': 'CSS',
        'correct_option': 'A',
        'marks': 1,
        'metadata_json': json.dumps({'options': [{'id': 'A', 'text': 'SQL'}, {'id': 'B', 'text': 'CSS'}]})
    }
    norm_drop = _normalize_quiz_question(dict(q_dropdown))
    assert norm_drop['is_coding'] is False
    assert norm_drop['question_type_norm'] == 'mscq_select'
    print("[PASS] Select Dropdown Normalized")

    # 4. Fill in the Blanks
    q_blank = {
        'question_id': 4,
        'question_type': 'fill_blank',
        'question_text': 'CPU stands for Central Processing ____',
        'correct_option': 'Unit',
        'marks': 1,
        'metadata_json': json.dumps({'acceptedAnswers': ['Unit', 'unit'], 'caseSensitive': False})
    }
    norm_blank = _normalize_quiz_question(dict(q_blank))
    assert norm_blank['is_coding'] is False
    assert norm_blank['question_type_norm'] == 'fill_blank'
    assert norm_blank['case_sensitive'] is False
    print("[PASS] Fill in the Blanks Normalized")

    # 5. True / False
    q_tf = {
        'question_id': 5,
        'question_type': 'true_false',
        'question_text': 'Python is an interpreted language.',
        'correct_option': 'True',
        'marks': 1,
        'metadata_json': json.dumps({'correctAnswer': 'True'})
    }
    norm_tf = _normalize_quiz_question(dict(q_tf))
    assert norm_tf['is_coding'] is False
    assert norm_tf['question_type_norm'] == 'true_false'
    print("[PASS] True / False Normalized")

    # 6. Coding Challenge
    q_code = {
        'question_id': 6,
        'question_type': 'code',
        'question_text': 'Write a function to return sum of two integers.',
        'test_input': '2 3',
        'test_output': '5',
        'marks': 10
    }
    norm_code = _normalize_quiz_question(dict(q_code))
    assert norm_code['is_coding'] is True, "Coding question must have is_coding=True"
    assert norm_code['question_type_norm'] == 'coding'
    print("[PASS] Coding Question Normalized")

    return [norm_single, norm_multi, norm_drop, norm_blank, norm_tf, norm_code]

def test_template_rendering(normalized_questions):
    print("\n--- 2. Testing Exam Console HTML Rendering ---")
    with app.test_request_context():
        from flask import render_template
        html = render_template('exam_console.html',
                               questions=normalized_questions,
                               attempt_id=9999,
                               quiz_meta={'duration_minutes': 30, 'title': 'Multi-Type Exam'},
                               saved_responses={},
                               user={'name': 'Test Student', 'roll_no': 'TS100'})
        
        # Verify Coding Shell is present for coding question (question_id: 6)
        assert 'mobile-prob-6' in html, "Coding shell must be rendered for question 6"
        assert 'ace-6' in html, "Ace editor must be rendered for question 6"

        # Verify Coding Shell is NOT present for quiz questions 1-5
        for q_id in [1, 2, 3, 4, 5]:
            assert f'ace-{q_id}' not in html, f"Ace editor should NOT be present for quiz question {q_id}"
            assert f'mobile-prob-{q_id}' not in html, f"Coding shell should NOT be present for quiz question {q_id}"

        # Verify the 5 specific question types are rendered
        assert 'Single Choice' in html
        assert 'radio-group' in html
        assert 'Multiple Choice' in html
        assert 'multi-group' in html
        assert 'Select Dropdown' in html
        assert 'exam-select-dropdown' in html
        assert 'Fill in the Blanks' in html
        assert 'exam-blank-input' in html
        assert 'True / False' in html
        assert 'tf-cards-grid' in html
        print("[PASS] All 5 Quiz Question Types + Coding Shell rendered distinctly with zero compiler leakage!")

if __name__ == '__main__':
    qs = test_normalization()
    test_template_rendering(qs)
    print("\n=== ALL UNIT & INTEGRATION TESTS PASSED SUCCESSFULLY! ===")
