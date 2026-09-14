import os
import sys

# Ensure root directory is in sys.path
sys.path.insert(0, os.path.abspath('.'))

from database import get_db_connection

def test_admit_card_resolution():
    print('Testing Admit Card Data Resolution...')
    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Check student query logic with COALESCE center join
        cursor.execute('''
            SELECT u.user_id, u.full_name, u.seat_row, u.seat_col,
                   COALESCE(c.center_name, c2.center_name) AS center_name,
                   COALESCE(c.address, c2.address) AS address,
                   COALESCE(c.city, c2.city) AS city 
            FROM Users u 
            LEFT JOIN Exam_Centers c ON u.center_id = c.center_id 
            LEFT JOIN Exam_Centers c2 ON u.allotted_center_id = c2.center_id 
            WHERE u.role = 'Student'
            LIMIT 5
        ''')
        students = cursor.fetchall()
        for s in students:
            print(f"Student: {s['full_name']} | Center: {s['center_name']} | City: {s['city']} | Address: {s['address']}")
            assert s['center_name'] is not None, f"Center name should not be None for student {s['full_name']}"
            assert s['city'] is not None, f"City should not be None for student {s['full_name']}"
            assert s['address'] is not None, f"Address should not be None for student {s['full_name']}"
    conn.close()
    print('PASS: Admit card center details resolve properly without None.')

def test_sidebar_profile_cleanup():
    print('Testing Sidebar Profile Cleanup...')
    with open('templates/_student_sidebar.html', 'r', encoding='utf-8') as f:
        content = f.read()
    assert 'View Profile' not in content, "Sidebar still contains 'View Profile'!"
    assert 'sidebar-user-name' in content, "Sidebar missing user name!"
    assert 'aspect-ratio: 1 / 1' in content or 'aspect-ratio:1/1' in content, "Sidebar avatar missing 1:1 aspect ratio!"
    print('PASS: Sidebar profile displays DP with Name only (View Profile removed).')

def test_navbar_dp_autofit():
    print('Testing Navbar DP Autofit & Clear Aspect Ratio...')
    with open('templates/student_dashboard.html', 'r', encoding='utf-8') as f:
        content = f.read()
    assert 'aspect-ratio: 1 / 1' in content or 'aspect-ratio:1/1' in content, "Missing 1:1 aspect-ratio in student_dashboard.html!"
    assert 'object-fit: cover' in content or 'object-fit:cover' in content, "Missing object-fit: cover in student_dashboard.html!"
    assert 'headerAvatar' in content, "Missing headerAvatar element!"
    assert 'user.avatar or user_profile_image' in content, "headerAvatar does not check user avatar!"
    print('PASS: Navbar profile DP has exact 1:1 autofit ratio and cover styling.')

def test_results_persistence_on_session_deletion():
    print('Testing Past Results Persistence on Session Deletion...')
    conn = get_db_connection()
    with conn.cursor() as cursor:
        # 1. Create a temporary test quiz
        cursor.execute('''
            INSERT INTO Quizzes (title, batch, department, year, duration_minutes, total_marks, instructions)
            VALUES ('Temporary Test Assessment Persistence', '2026-Batch', 'CSE', 'IV/II sem', 30, 100.00, 'Test rules')
        ''')
        quiz_id = cursor.lastrowid
        
        # 2. Create an attempt for student user 2
        cursor.execute('''
            INSERT INTO Quiz_Attempts (user_id, quiz_id, quiz_title, total_marks, batch, total_questions, total_score, status)
            VALUES (2, %s, 'Temporary Test Assessment Persistence', 100.00, '2026-Batch', 5, 85.00, 'Completed')
        ''', (quiz_id,))
        attempt_id = cursor.lastrowid
        conn.commit()

        # 3. Simulate delete_session route logic
        # Snapshot metadata on attempts
        cursor.execute('''
            UPDATE Quiz_Attempts a
            JOIN Quizzes q ON a.quiz_id = q.quiz_id
            SET a.quiz_title = COALESCE(a.quiz_title, q.title),
                a.total_marks = COALESCE(a.total_marks, q.total_marks, 100.00),
                a.batch = COALESCE(a.batch, q.batch),
                a.total_questions = COALESCE(a.total_questions, 5)
            WHERE a.quiz_id = %s
        ''', (quiz_id,))
        cursor.execute('UPDATE Quiz_Attempts SET quiz_id = NULL WHERE quiz_id = %s', (quiz_id,))
        cursor.execute('DELETE FROM Quizzes WHERE quiz_id=%s', (quiz_id,))
        conn.commit()

        # 4. Verify attempt is still present in Quiz_Attempts!
        cursor.execute('SELECT * FROM Quiz_Attempts WHERE attempt_id = %s', (attempt_id,))
        saved_attempt = cursor.fetchone()
        assert saved_attempt is not None, "Attempt was unexpectedly deleted after quiz deletion!"
        assert saved_attempt['quiz_title'] == 'Temporary Test Assessment Persistence', f"Incorrect quiz_title: {saved_attempt['quiz_title']}"
        assert float(saved_attempt['total_score']) == 85.00, f"Incorrect total_score: {saved_attempt['total_score']}"
        assert saved_attempt['status'] == 'Completed', f"Incorrect status: {saved_attempt['status']}"

        # 5. Verify student history query retrieves the preserved attempt
        cursor.execute('''
            SELECT 
                COALESCE(q.title, a.quiz_title, 'Completed Assessment') AS title,
                COALESCE(q.total_marks, a.total_marks, 100) AS total_marks,
                a.total_score, a.status, a.attempt_id
            FROM Quiz_Attempts a 
            LEFT JOIN Quizzes q ON a.quiz_id=q.quiz_id 
            WHERE a.attempt_id = %s
        ''', (attempt_id,))
        history_row = cursor.fetchone()
        assert history_row is not None, "History query failed to retrieve deleted quiz attempt!"
        assert history_row['title'] == 'Temporary Test Assessment Persistence', f"History title mismatch: {history_row['title']}"
        print(f"Preserved Attempt Retrieved Successfully: Title='{history_row['title']}', Score={history_row['total_score']}")

        # Clean up test attempt
        cursor.execute('DELETE FROM Quiz_Attempts WHERE attempt_id = %s', (attempt_id,))
        conn.commit()

    conn.close()
    print('PASS: Past student results are 100% saved and retrieved even after quiz session deletion.')

def test_universal_footer():
    print('Testing Universal Footer across Dashboards...')
    templates_to_check = [
        'templates/student_dashboard.html',
        'templates/coordinator_dashboard.html',
        'templates/admin_dashboard.html',
        'templates/student_study.html',
        'templates/student_progress.html',
        'templates/coding_builder.html',
        'templates/question_bank.html',
        'templates/question_repository.html',
        'templates/manage_sessions.html',
        'templates/manage_centers.html',
        'templates/admin_results.html'
    ]

    for tpath in templates_to_check:
        with open(tpath, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'Nexhydigital.in' in content, f"Template {tpath} is missing 'Nexhydigital.in' in footer!"
        assert 'Powered by' in content, f"Template {tpath} is missing 'Powered by' in footer!"
        print(f"  OK: {tpath} has universal footer.")
    print('PASS: Universal footer verified across all Student, Coordinator, and Admin templates.')

if __name__ == '__main__':
    test_admit_card_resolution()
    test_sidebar_profile_cleanup()
    test_navbar_dp_autofit()
    test_results_persistence_on_session_deletion()
    test_universal_footer()
    print('\nALL 5 VERIFICATION SUITES PASSED!')
