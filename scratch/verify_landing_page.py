import os
import sys
import json

# Add root directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routes.home import get_monotonic_stats, METRICS_FILE

def test_monotonic_counter():
    print("Testing Monotonic Non-Dropping Counter Logic...")
    # Clean test metrics file if needed or mock it
    if os.path.exists(METRICS_FILE):
        try:
            os.remove(METRICS_FILE)
        except Exception:
            pass

    # Baseline 0
    s0 = get_monotonic_stats({'students': 0, 'exams': 0, 'quizzes': 0})
    assert s0['students'] == 0
    assert s0['exams'] == 0
    assert s0['quizzes'] == 0
    print("  OK: Baseline 0 stats handled.")

    # Growth milestone: 15 students, 8 exams, 3 quizzes
    s1 = get_monotonic_stats({'students': 15, 'exams': 8, 'quizzes': 3})
    assert s1['students'] == 15
    assert s1['exams'] == 8
    assert s1['quizzes'] == 3
    print("  OK: Stats increase recorded accurately (15, 8, 3).")

    # Drop attempt (e.g. DB wiped or test records deleted: 2 students, 0 exams, 1 quiz)
    s2 = get_monotonic_stats({'students': 2, 'exams': 0, 'quizzes': 1})
    assert s2['students'] == 15, f"Expected monotonic 15 students, got {s2['students']}"
    assert s2['exams'] == 8, f"Expected monotonic 8 exams, got {s2['exams']}"
    assert s2['quizzes'] == 3, f"Expected monotonic 3 quizzes, got {s2['quizzes']}"
    print("  OK: Count DID NOT DROP when incoming stats decreased (Monotonic guarantee preserved)!")

    # Further growth in one metric only
    s3 = get_monotonic_stats({'students': 15, 'exams': 25, 'quizzes': 3})
    assert s3['students'] == 15
    assert s3['exams'] == 25
    assert s3['quizzes'] == 3
    print("  OK: Partial milestone update verified (exams increased to 25, others maintained).")
    print("PASS: Monotonic Counter Logic Verified Successfully.\n")

def test_template_content():
    print("Testing Home Template HTML Content & Standards...")
    with open('templates/home.html', 'r', encoding='utf-8') as f:
        html = f.read()

    # Core user requirements
    assert 'Active Learners' in html, "Missing 'Active Learners'"
    assert 'Exams Completed' in html, "Missing 'Exams Completed'"
    assert 'Live Challenges' in html, "Missing 'Live Challenges'"
    assert 'plus-symbol' in html or '+' in html, "Missing '+' symbol notation"
    assert 'Nexhydigital.in' in html, "Missing 'Nexhydigital.in'"
    assert 'Powered by' in html, "Missing 'Powered by'"
    assert 'https://nexhydigital.in' in html, "Missing link to https://nexhydigital.in"

    # Universal footer check
    assert '&copy; 2026 QuizMaster. All Rights Reserved. Powered by' in html, "Missing standardized universal copyright line"

    # Monotonic local storage code check
    assert 'localStorage.getItem(\'qm_peak_students\')' in html, "Missing client-side peak students localStorage logic"
    assert 'localStorage.getItem(\'qm_peak_exams\')' in html, "Missing client-side peak exams localStorage logic"
    assert 'localStorage.getItem(\'qm_peak_quizzes\')' in html, "Missing client-side peak quizzes localStorage logic"

    # Preserved components
    assert 'bannerModalBackdrop' in html, "Missing preserved banner modal"

    print("  OK: All required text, counters, links, and footer signatures verified.")
    print("PASS: Template verification passed.\n")

def test_flask_app_rendering():
    print("Testing Flask Route / rendering...")
    from main import app
    app.config['TESTING'] = True
    with app.test_client() as client:
        res = client.get('/')
        assert res.status_code == 200, f"Expected HTTP 200, got {res.status_code}"
        text = res.get_data(as_text=True)
        assert 'QuizMaster' in text
        assert 'Active Learners' in text
        assert 'Exams Completed' in text
        assert 'Live Challenges' in text
        assert 'Nexhydigital.in' in text
        assert 'Powered by' in text
        print("  OK: Route '/' returns HTTP 200 and renders complete landing page.")

        # Test API endpoint
        api_res = client.get('/api/platform_stats')
        assert api_res.status_code == 200
        api_json = api_res.get_json()
        assert api_json['status'] == 'success'
        assert 'stats' in api_json
        assert 'display' in api_json
        print(f"  OK: Route '/api/platform_stats' returns HTTP 200: {api_json['display']}")

    print("PASS: Flask Route Rendering Passed.\n")

if __name__ == '__main__':
    test_monotonic_counter()
    test_template_content()
    test_flask_app_rendering()
    print("==================================================")
    print("ALL LANDING PAGE SUITES PASSED SUCCESSFULLY!")
    print("==================================================")
