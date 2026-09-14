import os
import sys

# Add root directory to python path
sys.path.insert(0, os.path.abspath('.'))

from main import app
from flask import render_template
from routes.quiz import _normalize_quiz_question

def test_normalization():
    print("--- 1. Testing Question Normalization ---")
    # Test 1: Fill in the Blanks with spaces and mixed case
    q1 = {
        'question_id': 101,
        'question_type': 'Fill in the Blanks',
        'question_text': 'The capital of France is _______.',
        'option_a': '', 'option_b': '', 'option_c': '', 'option_d': '',
        'correct_option': 'Paris',
        'marks': 2,
        'metadata_json': '{"caseSensitive": false, "acceptedAnswers": ["Paris"]}'
    }
    norm1 = _normalize_quiz_question(q1)
    assert norm1['question_type_norm'] == 'fill_blank', f"Expected fill_blank, got {norm1['question_type_norm']}"
    assert not norm1['is_coding'], "Should not be coding"
    assert norm1['accepted_answers'] == ['Paris']
    print("[PASS] Test 1: 'Fill in the Blanks' normalized correctly to 'fill_blank'")

    # Test 2: Question with 0 options that was marked as 'mscq_single' by mistake
    q2 = {
        'question_id': 102,
        'question_type': 'single',
        'question_text': 'Type the output of print(2**3): _______',
        'option_a': None, 'option_b': '', 'option_c': '', 'option_d': '',
        'correct_option': '8',
        'marks': 1,
        'metadata_json': None
    }
    norm2 = _normalize_quiz_question(q2)
    assert norm2['question_type_norm'] == 'fill_blank', f"Expected fallback to fill_blank for 0-option question, got {norm2['question_type_norm']}"
    print("[PASS] Test 2: 0-option question fallback correctly normalized to 'fill_blank'")

    # Test 3: Standard single choice MCQ
    q3 = {
        'question_id': 103,
        'question_type': 'mscq_single',
        'question_text': 'What is Python?',
        'option_a': 'Language', 'option_b': 'Snake', 'option_c': 'Car', 'option_d': 'Food',
        'correct_option': 'A',
        'marks': 1
    }
    norm3 = _normalize_quiz_question(q3)
    assert norm3['question_type_norm'] == 'mscq_single'
    assert len(norm3['shuffled_options']) == 4
    print("[PASS] Test 3: 'mscq_single' options configured correctly")

    # Test 4: True / False question
    q4 = {
        'question_id': 104,
        'question_type': 'True / False',
        'question_text': 'HTML is a programming language.',
        'correct_option': 'False',
        'marks': 1
    }
    norm4 = _normalize_quiz_question(q4)
    assert norm4['question_type_norm'] == 'true_false'
    print("[PASS] Test 4: 'True / False' normalized correctly")

def test_template_rendering():
    print("\n--- 2. Testing exam_console.html Rendering ---")
    with app.test_request_context():
        q_blank = _normalize_quiz_question({
            'question_id': 1,
            'question_type': 'fill in the blanks',
            'question_text': 'Sun rises in the _______.',
            'correct_option': 'East',
            'marks': 1
        })
        q_mcq = _normalize_quiz_question({
            'question_id': 2,
            'question_type': 'mscq_single',
            'question_text': '2 + 2 = ?',
            'option_a': '3', 'option_b': '4', 'option_c': '5', 'option_d': '6',
            'correct_option': 'B',
            'marks': 1
        })
        q_tf = _normalize_quiz_question({
            'question_id': 3,
            'question_type': 'true_false',
            'question_text': 'The Earth is round.',
            'correct_option': 'True',
            'marks': 1
        })

        questions = [q_blank, q_mcq, q_tf]
        quiz_meta = {
            'title': 'Midterm Comprehensive Examination',
            'duration_minutes': 45
        }

        html = render_template(
            'exam_console.html',
            questions=questions,
            attempt_id=999,
            quiz_meta=quiz_meta,
            saved_responses={},
            user={'full_name': 'Test Student', 'user_id': 42}
        )

        # 1. Verify Horizontal Question Bar
        assert 'class="h-qnav-container"' in html, "Horizontal question nav bar missing"
        assert 'id="hpill-1"' in html, "hpill for question 1 missing"
        assert 'id="hpill-2"' in html, "hpill for question 2 missing"
        assert 'id="hpill-3"' in html, "hpill for question 3 missing"
        print("[PASS] Horizontal question nav strip (.h-qnav-container, hpill) rendered successfully")

        # 2. Verify Theme Switcher
        assert 'btn-theme-toggle' in html, "Theme toggle button missing"
        assert 'toggleGlobalTheme()' in html, "toggleGlobalTheme() handler missing"
        assert 'body.light-theme' in html, "body.light-theme CSS missing"
        print("[PASS] Global Light/Dark Theme Switcher button and CSS styles verified")

        # 3. Verify 'Review and Submit' Rename
        assert 'Review and Submit' in html, "'Review and Submit' text missing from buttons"
        assert 'btn-finish-exam' in html, "Submit button missing"
        print("[PASS] Button renamed to 'Review and Submit' in top bar and sidebar drawer")

        # 4. Verify Fill in the Blanks Answer Writing Box
        assert 'id="blank-input-1"' in html, "Fill in the blank input box for question 1 missing"
        assert 'class="exam-blank-input"' in html, "exam-blank-input class missing"
        assert 'handleBlankInput(\'1\'' in html or 'handleBlankInput("1"' in html, "handleBlankInput trigger missing"
        assert 'clearBlankInput(\'1\'' in html or 'clearBlankInput("1"' in html, "clearBlankInput trigger missing"
        print("[PASS] Fill in the Blanks answer writing box (input, clear button, auto-save) verified")

        # 5. Verify Device Auto-fit / Responsive support
        assert 'viewport-fit=cover' in html, "viewport-fit=cover missing"
        assert '@supports (padding: max(0px))' in html, "iOS Safari safe-area insets missing"
        assert '@media (max-width: 991px)' in html, "Tablet responsive media query missing"
        assert '@media (max-width: 600px)' in html, "Mobile responsive media query missing"
        print("[PASS] Universal Auto-fit device ratio support (iOS Safari, Android, Tablet, Desktop) verified")

if __name__ == '__main__':
    test_normalization()
    test_template_rendering()
    print("\nALL 5 REQUIREMENTS FULLY VERIFIED AND PASSING!")
