"""
QuizMaster Production WSGI Entrypoint.
Compatible with Gunicorn, Waitress, uWSGI, and containerized deployments.

Run with Waitress (Windows/Cross-platform):
    python wsgi.py

Run with Gunicorn (Linux/Containers):
    gunicorn -w 4 -b 0.0.0.0:5000 wsgi:application
"""

import os
import sys

# Ensure repository root is on Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app as application

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    host = os.getenv('FLASK_HOST', '0.0.0.0')

    try:
        from waitress import serve
        print(f"Starting QuizMaster with Waitress production WSGI server on {host}:{port}...")
        serve(application, host=host, port=port, threads=6)
    except ImportError:
        print(f"Waitress not found. Running with Flask production runner on {host}:{port}...")
        application.run(host=host, port=port, debug=False)
