import sys, os
sys.path.insert(0, os.path.abspath('.'))
from utils import get_db_connection
from routes.quiz import _normalize_quiz_question
import json

conn = get_db_connection()
cursor = conn.cursor()
cursor.execute('SELECT * FROM Questions WHERE quiz_id = 8 ORDER BY question_id ASC')
rows = cursor.fetchall()
conn.close()

print(f"Total questions for quiz 8: {len(rows)}")
for r in rows:
    norm = _normalize_quiz_question(dict(r))
    print("ID:", norm['question_id'], "| raw_type:", r.get('question_type'), "| norm_type:", norm.get('question_type_norm'), "| opts_count:", len(norm.get('shuffled_options', [])), "| is_coding:", norm.get('is_coding'), "| module:", r.get('module'))
