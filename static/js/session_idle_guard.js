/**
 * QuizMaster Enterprise SaaS - Idle Session Security Guard
 * Enforces 25-minute inactivity auto-logout for Student and Coordinator portals.
 */
(function() {
    // 25 minutes total, warning at 24 minutes (60s countdown)
    const IDLE_TIMEOUT_SECONDS = 25 * 60; // 1500s
    const WARNING_BEFORE_SECONDS = 60;     // 60s
    const WARNING_TRIGGER_SECONDS = IDLE_TIMEOUT_SECONDS - WARNING_BEFORE_SECONDS; // 1440s
    const HEARTBEAT_INTERVAL_SECONDS = 120; // Ping backend at most once every 2 minutes

    let secondsIdle = 0;
    let lastHeartbeatTime = Date.now();
    let warningVisible = false;
    let countdownInterval = null;

    // Create Warning Modal / Banner in DOM
    function createWarningModal() {
        if (document.getElementById('qm-idle-warning-modal')) return;

        const modal = document.createElement('div');
        modal.id = 'qm-idle-warning-modal';
        modal.style.cssText = `
            display: none;
            position: fixed;
            bottom: 24px;
            right: 24px;
            z-index: 999999;
            background: #ffffff;
            color: #0f172a;
            border: 1px solid #cbd5e1;
            border-left: 5px solid #f59e0b;
            border-radius: 12px;
            padding: 20px 24px;
            box-shadow: 0 20px 35px -5px rgba(15, 23, 42, 0.18), 0 0 0 1px rgba(0,0,0,0.05);
            max-width: 380px;
            font-family: 'Plus Jakarta Sans', 'Inter', sans-serif;
            animation: slideUpWarning 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        `;

        modal.innerHTML = `
            <style>
                @keyframes slideUpWarning {
                    from { transform: translateY(20px); opacity: 0; }
                    to { transform: translateY(0); opacity: 1; }
                }
            </style>
            <div style="display: flex; align-items: flex-start; gap: 14px;">
                <div style="font-size: 22px; color: #d97706; line-height: 1;">
                    <i class="fas fa-clock-rotate-left"></i>
                </div>
                <div style="flex: 1;">
                    <h4 style="margin: 0 0 4px 0; font-size: 15px; font-weight: 700; color: #0f172a;">
                        Inactivity Notice
                    </h4>
                    <p style="margin: 0 0 12px 0; font-size: 13px; color: #475569; line-height: 1.45;">
                        You have been inactive. For your security, your session will end in <strong id="qm-idle-countdown" style="color: #b45309; font-weight: 800;">60</strong>s.
                    </p>
                    <div style="display: flex; gap: 8px;">
                        <button id="qm-stay-logged-in-btn" style="
                            background: #4f46e5;
                            color: #ffffff;
                            border: none;
                            padding: 6px 14px;
                            border-radius: 6px;
                            font-size: 12px;
                            font-weight: 600;
                            cursor: pointer;
                        ">
                            Stay Logged In
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        document.getElementById('qm-stay-logged-in-btn').addEventListener('click', function() {
            resetIdleTimer();
            sendHeartbeat(true);
        });
    }

    // Send heartbeat to backend
    function sendHeartbeat(force = false) {
        const now = Date.now();
        if (!force && (now - lastHeartbeatTime < HEARTBEAT_INTERVAL_SECONDS * 1000)) {
            return;
        }
        lastHeartbeatTime = now;

        fetch('/api/session/heartbeat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        })
        .then(res => res.json())
        .then(data => {
            if (data && data.error === 'concurrent_login') {
                // Logged in from another device
                window.location.href = '/login?reason=concurrent_login';
            }
        })
        .catch(() => {});
    }

    // Reset idle timer upon user action
    function resetIdleTimer() {
        secondsIdle = 0;
        if (warningVisible) {
            hideWarning();
        }
        sendHeartbeat(false);
    }

    // Show warning at 24 minutes (60s countdown)
    function showWarning() {
        warningVisible = true;
        createWarningModal();
        const modal = document.getElementById('qm-idle-warning-modal');
        if (modal) modal.style.display = 'block';

        let remaining = WARNING_BEFORE_SECONDS;
        const countdownEl = document.getElementById('qm-idle-countdown');
        if (countdownEl) countdownEl.innerText = remaining;

        if (countdownInterval) clearInterval(countdownInterval);
        countdownInterval = setInterval(function() {
            remaining--;
            if (countdownEl) countdownEl.innerText = Math.max(0, remaining);
            if (remaining <= 0) {
                clearInterval(countdownInterval);
                logoutDueToTimeout();
            }
        }, 1000);
    }

    function hideWarning() {
        warningVisible = false;
        if (countdownInterval) clearInterval(countdownInterval);
        const modal = document.getElementById('qm-idle-warning-modal');
        if (modal) modal.style.display = 'none';
    }

    function logoutDueToTimeout() {
        window.location.href = '/logout?reason=timeout';
    }

    // Master second-by-second ticker
    setInterval(function() {
        secondsIdle++;
        if (secondsIdle >= WARNING_TRIGGER_SECONDS && !warningVisible) {
            showWarning();
        }
        if (secondsIdle >= IDLE_TIMEOUT_SECONDS) {
            logoutDueToTimeout();
        }
    }, 1000);

    // Active user event listeners (debounced)
    const userEvents = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart'];
    let debounceTimer = null;
    userEvents.forEach(function(evt) {
        window.addEventListener(evt, function() {
            if (!debounceTimer) {
                debounceTimer = setTimeout(function() {
                    debounceTimer = null;
                    resetIdleTimer();
                }, 1000);
            }
        }, { passive: true });
    });

    // Initial heartbeat
    setTimeout(function() {
        sendHeartbeat(true);
    }, 2000);

})();
