import os
import sys
import subprocess
import tempfile
import shutil
import time
import requests
from utils import normalize_judge_output

JUDGE0_URL = os.getenv('JUDGE0_URL', 'http://localhost:2358').rstrip('/')

JUDGE0_LANG_IDS = {
    'python': 71,       # Python (3.8.1)
    'py': 71,
    'python3': 71,
    'javascript': 63,   # JavaScript (Node.js 12.14.0)
    'js': 63,
    'c': 50,            # C (GCC 9.2.0)
    'cpp': 54,          # C++ (GCC 9.2.0)
    'c++': 54,
    'java': 62,         # Java (OpenJDK 13.0.1)
}

def is_judge0_online():
    """Quick check if Judge0 cluster is up and running."""
    try:
        r = requests.get(f"{JUDGE0_URL}/system_info", timeout=1.2)
        return r.status_code == 200
    except Exception:
        return False

def run_via_judge0(code, language, stdin_data='', timeout=3.0):
    """Executes code inside the Judge0 sandboxed worker cluster."""
    lang_id = JUDGE0_LANG_IDS.get(language.lower(), 71)
    payload = {
        "source_code": code,
        "language_id": lang_id,
        "stdin": stdin_data or "",
        "cpu_time_limit": float(timeout),
        "memory_limit": 128000,
        "redirect_stderr_to_stdout": False
    }

    resp = requests.post(f"{JUDGE0_URL}/submissions?wait=true", json=payload, timeout=timeout + 4.0)
    data = resp.json()

    stdout = data.get('stdout') or ''
    stderr = data.get('stderr') or ''
    compile_output = data.get('compile_output') or ''
    status_id = data.get('status_id')
    status_desc = (data.get('status') or {}).get('description', '')

    # Map status
    if status_id == 3 or status_desc == 'Accepted':
        verdict = 'Accepted'
    elif status_id == 5 or 'Time Limit' in status_desc:
        verdict = 'Time Limit Exceeded'
    elif status_id == 6 or 'Compilation' in status_desc:
        verdict = 'Compilation Error'
    else:
        verdict = status_desc or 'Runtime Error'

    combined_err = compile_output or stderr
    return {
        'stdout': stdout,
        'stderr': combined_err,
        'verdict': verdict,
        'time': data.get('time'),
        'memory': data.get('memory')
    }

def run_locally(code, language, stdin_data='', timeout=3.0):
    """
    Built-in resilient local runner used when Judge0 server is offline.
    Uses isolated temp directory and strict subprocess timeouts.
    """
    lang = language.lower().strip()
    temp_dir = tempfile.mkdtemp(prefix='quiz_run_')
    
    try:
        if lang in ('python', 'py', 'python3'):
            code_file = os.path.join(temp_dir, 'solution.py')
            with open(code_file, 'w', encoding='utf-8') as f:
                f.write(code)

            cmd = [sys.executable, '-I', '-B', code_file]
            proc = subprocess.run(
                cmd,
                input=stdin_data,
                text=True,
                capture_output=True,
                timeout=timeout,
                cwd=temp_dir
            )
            return {
                'stdout': proc.stdout or '',
                'stderr': proc.stderr or '',
                'verdict': 'Accepted' if proc.returncode == 0 else 'Runtime Error'
            }

        elif lang in ('javascript', 'js'):
            node_path = shutil.which('node')
            if not node_path:
                return {'stdout': '', 'stderr': 'Node.js is not installed locally on the host.', 'verdict': 'Runtime Error'}
            code_file = os.path.join(temp_dir, 'solution.js')
            with open(code_file, 'w', encoding='utf-8') as f:
                f.write(code)

            proc = subprocess.run(
                [node_path, code_file],
                input=stdin_data,
                text=True,
                capture_output=True,
                timeout=timeout,
                cwd=temp_dir
            )
            return {
                'stdout': proc.stdout or '',
                'stderr': proc.stderr or '',
                'verdict': 'Accepted' if proc.returncode == 0 else 'Runtime Error'
            }

        elif lang in ('c', 'cpp', 'c++'):
            is_cpp = lang in ('cpp', 'c++')
            compiler = shutil.which('g++') if is_cpp else shutil.which('gcc')
            if not compiler:
                return {'stdout': '', 'stderr': f"{'g++' if is_cpp else 'gcc'} compiler not found on host. Please start Judge0.", 'verdict': 'Compilation Error'}
            
            src_ext = '.cpp' if is_cpp else '.c'
            src_file = os.path.join(temp_dir, f"solution{src_ext}")
            out_bin = os.path.join(temp_dir, 'solution.exe' if os.name == 'nt' else 'solution')
            with open(src_file, 'w', encoding='utf-8') as f:
                f.write(code)

            # Compile
            comp_res = subprocess.run(
                [compiler, src_file, '-o', out_bin],
                capture_output=True,
                text=True,
                timeout=5.0,
                cwd=temp_dir
            )
            if comp_res.returncode != 0:
                return {'stdout': '', 'stderr': comp_res.stderr or 'Compilation failed.', 'verdict': 'Compilation Error'}

            # Run
            proc = subprocess.run(
                [out_bin],
                input=stdin_data,
                text=True,
                capture_output=True,
                timeout=timeout,
                cwd=temp_dir
            )
            return {
                'stdout': proc.stdout or '',
                'stderr': proc.stderr or '',
                'verdict': 'Accepted' if proc.returncode == 0 else 'Runtime Error'
            }

        elif lang == 'java':
            javac = shutil.which('javac')
            java = shutil.which('java')
            if not javac or not java:
                return {'stdout': '', 'stderr': 'Java SDK (javac/java) not found on host. Please start Judge0.', 'verdict': 'Compilation Error'}

            src_file = os.path.join(temp_dir, 'Main.java')
            with open(src_file, 'w', encoding='utf-8') as f:
                f.write(code)

            comp_res = subprocess.run(
                [javac, 'Main.java'],
                capture_output=True,
                text=True,
                timeout=6.0,
                cwd=temp_dir
            )
            if comp_res.returncode != 0:
                return {'stdout': '', 'stderr': comp_res.stderr or 'Java compilation failed.', 'verdict': 'Compilation Error'}

            proc = subprocess.run(
                [java, '-cp', temp_dir, 'Main'],
                input=stdin_data,
                text=True,
                capture_output=True,
                timeout=timeout,
                cwd=temp_dir
            )
            return {
                'stdout': proc.stdout or '',
                'stderr': proc.stderr or '',
                'verdict': 'Accepted' if proc.returncode == 0 else 'Runtime Error'
            }

        else:
            return {'stdout': '', 'stderr': f"Unsupported language: {language}", 'verdict': 'Runtime Error'}

    except subprocess.TimeoutExpired:
        return {
            'stdout': '',
            'stderr': f"Time Limit Exceeded ({timeout}s)",
            'verdict': 'Time Limit Exceeded'
        }
    except Exception as e:
        return {
            'stdout': '',
            'stderr': f"Execution error: {str(e)}",
            'verdict': 'Runtime Error'
        }
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

def execute_code(code, language, stdin_data='', timeout=3.0):
    """
    Executes code using Judge0 if active; otherwise automatically falls back to safe local execution.
    """
    if is_judge0_online():
        try:
            return run_via_judge0(code, language, stdin_data, timeout)
        except Exception:
            pass # Fallback to local
    return run_locally(code, language, stdin_data, timeout)
