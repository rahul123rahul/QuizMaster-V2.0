import os
import sys
import time

# Add repo root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from session_manager import (
    register_user_session, 
    validate_user_session, 
    invalidate_user_session,
    is_inactive,
    INACTIVITY_TIMEOUT_SECONDS
)

def test_session_manager_unit():
    print("\n--- 1. Testing session_manager unit functions ---")
    user_id = 99999
    
    # Register Device 1
    token1 = register_user_session(user_id, 'Student')
    assert token1 is not None and len(token1) > 10
    assert validate_user_session(user_id, token1) is True
    print("  OK: Device 1 registered with unique token.")

    # Register Device 2 (same user logs in on new device)
    token2 = register_user_session(user_id, 'Student')
    assert token2 != token1
    assert validate_user_session(user_id, token2) is True
    # Device 1 token MUST now be invalid!
    assert validate_user_session(user_id, token1) is False
    print("  OK: Single-device enforcement: Device 1 token superseded by Device 2.")

    # Invalidate session on logout
    invalidate_user_session(user_id)
    assert validate_user_session(user_id, token2) is False
    print("  OK: Invalidation clears active token on logout.")

    # Timeout check (25 minutes = 1500 seconds)
    assert INACTIVITY_TIMEOUT_SECONDS == 1500
    now = time.time()
    assert is_inactive(now - 100) is False   # 100s ago -> active
    assert is_inactive(now - 1400) is False  # 23.3 mins ago -> active
    assert is_inactive(now - 1501) is True   # 25 mins + 1s -> inactive!
    assert is_inactive(now - 3600) is True   # 1 hr ago -> inactive!
    print("  OK: 25-minute inactivity calculation verified.")
    print("PASS: Session manager unit tests passed.")

def test_single_device_concurrent_prevention_http():
    print("\n--- 2. Testing HTTP Enforcement of Single Device Login ---")
    app.config['TESTING'] = True
    
    # Client A (Device 1)
    client_a = app.test_client()
    # Client B (Device 2)
    client_b = app.test_client()

    user_id = 88888
    # Device 1 logs in
    token_a = register_user_session(user_id, 'Student')
    with client_a.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['role'] = 'Student'
        sess['session_token'] = token_a
        sess['last_activity'] = time.time()

    # Device 1 can access /student (or mock request)
    res_a1 = client_a.get('/student')
    assert res_a1.status_code in [200, 302]
    assert 'reason=concurrent_login' not in res_a1.headers.get('Location', '')
    print("  OK: Device 1 has active access.")

    # Device 2 logs in (same user, new token)
    token_b = register_user_session(user_id, 'Student')
    with client_b.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['role'] = 'Student'
        sess['session_token'] = token_b
        sess['last_activity'] = time.time()

    # Device 2 has active access
    res_b = client_b.get('/student')
    assert 'reason=concurrent_login' not in res_b.headers.get('Location', '')
    print("  OK: Device 2 successfully logged in.")

    # Device 1 now tries to make a request:
    res_a2 = client_a.get('/student')
    assert res_a2.status_code == 302
    assert 'reason=concurrent_login' in res_a2.headers.get('Location', ''), f"Expected concurrent_login redirect, got {res_a2.headers.get('Location')}"
    print("  OK: Device 1 was blocked and redirected with reason=concurrent_login!")

    # Verify Device 1 session was cleared
    with client_a.session_transaction() as sess:
        assert 'user_id' not in sess
    print("  OK: Device 1 session was completely cleared.")
    print("PASS: Single-device HTTP enforcement test passed.")

def test_25_min_inactivity_timeout_http():
    print("\n--- 3. Testing 25-Minute Inactivity Timeout HTTP Enforcement ---")
    app.config['TESTING'] = True
    client = app.test_client()
    user_id = 77777

    token = register_user_session(user_id, 'Coordinator')
    now = time.time()

    # 1. Active access within 25 minutes (e.g. 5 minutes ago)
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['role'] = 'Coordinator'
        sess['session_token'] = token
        sess['last_activity'] = now - 300 # 5 minutes ago

    res_active = client.get('/coordinator/')
    assert 'reason=timeout' not in res_active.headers.get('Location', '')
    print("  OK: Request within 25 minutes is allowed.")

    # 2. Inactive request (26 minutes ago)
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['role'] = 'Coordinator'
        sess['session_token'] = token
        sess['last_activity'] = now - 1560 # 26 minutes ago

    res_timed_out = client.get('/coordinator/')
    assert res_timed_out.status_code == 302
    assert 'reason=timeout' in res_timed_out.headers.get('Location', ''), f"Expected timeout redirect, got {res_timed_out.headers.get('Location')}"
    print("  OK: Request after 26 minutes without activity redirected to /login?reason=timeout!")

    # Verify session was cleared
    with client.session_transaction() as sess:
        assert 'user_id' not in sess
    print("  OK: User session was completely cleared on timeout.")
    print("PASS: 25-minute inactivity timeout HTTP test passed.")

def test_heartbeat_api():
    print("\n--- 4. Testing /api/session/heartbeat ---")
    app.config['TESTING'] = True
    client = app.test_client()
    user_id = 66666

    token = register_user_session(user_id, 'Student')
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['role'] = 'Student'
        sess['session_token'] = token
        sess['last_activity'] = time.time()

    res = client.post('/api/session/heartbeat')
    assert res.status_code == 200
    data = res.get_json()
    assert data['active'] is True
    assert data['timeout_seconds'] == 1500
    print(f"  OK: Heartbeat successful: {data}")

    # Test heartbeat when superseded on another device
    register_user_session(user_id, 'Student') # New token generated
    res_stale = client.post('/api/session/heartbeat')
    assert res_stale.status_code == 401
    data_stale = res_stale.get_json()
    assert data_stale['error'] == 'concurrent_login'
    print("  OK: Heartbeat detects concurrent login and returns error: concurrent_login.")
    print("PASS: Heartbeat API test passed.")

if __name__ == '__main__':
    test_session_manager_unit()
    test_single_device_concurrent_prevention_http()
    test_25_min_inactivity_timeout_http()
    test_heartbeat_api()
    print("\n=======================================================")
    print("ALL SESSION SECURITY & CONCURRENCY TESTS PASSED (25 MIN)!")
    print("=======================================================")
