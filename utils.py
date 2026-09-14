from flask import request, session, current_app, url_for
from datetime import timedelta, datetime, time
import base64
import random
import csv
import io
import docx
import os
from werkzeug.utils import secure_filename
import requests
import sys
import secrets
from difflib import SequenceMatcher
import time
import threading
import json
import re
from dotenv import load_dotenv
from database import get_db_connection
from certificate_generator import generate_certificate_pdf

# Global configs from app.py
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_PRIMARY_MODEL = os.getenv('GROQ_MODEL', 'meta-llama/llama-4-scout-17b-16e-instruct')
GROQ_FALLBACK_MODELS = [
    GROQ_PRIMARY_MODEL,
    'llama-3.1-8b-instant',
]
GROQ_REQUEST_LOCK = threading.Lock()
GROQ_NEXT_ALLOWED_AT = 0.0
MAX_AI_QUESTION_COUNT = 30
AI_BATCH_CHUNK_SIZE = 5
AI_PREVIEW_CACHE = {}
AI_PREVIEW_CACHE_TTL_SECONDS = 3600
QUESTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["question", "a", "b", "c", "d", "correct", "marks"],
    "properties": {
        "question": {"type": "string"},
        "a": {"type": "string"},
        "b": {"type": "string"},
        "c": {"type": "string"},
        "d": {"type": "string"},
        "correct": {"type": "string", "enum": ["A", "B", "C", "D"]},
        "marks": {"type": "integer", "minimum": 1, "maximum": 10}
    }
}
QUESTION_LIST_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "maxItems": MAX_AI_QUESTION_COUNT,
    "items": QUESTION_SCHEMA,
}

TEST_CASE_SEPARATOR = re.compile(r'(?:\r?\n)\s*(?:---+|===+|\|\|\|)\s*(?:\r?\n)')

def prune_ai_preview_cache():
    now = time.time()
    expired_tokens = [
        token for token, item in AI_PREVIEW_CACHE.items()
        if now - item.get('created_at', 0) > AI_PREVIEW_CACHE_TTL_SECONDS
    ]

    for token in expired_tokens:
        AI_PREVIEW_CACHE.pop(token, None)

    if len(AI_PREVIEW_CACHE) > 32:
        oldest_tokens = sorted(
            AI_PREVIEW_CACHE,
            key=lambda token: AI_PREVIEW_CACHE[token].get('created_at', 0)
        )[:-32]
        for token in oldest_tokens:
            AI_PREVIEW_CACHE.pop(token, None)

def cache_ai_preview_state(preview_state):
    prune_ai_preview_cache()
    preview_token = secrets.token_urlsafe(16)
    AI_PREVIEW_CACHE[preview_token] = {
        'created_at': time.time(),
        'state': preview_state,
    }
    session['ai_preview_token'] = preview_token
    return preview_token

def get_cached_ai_preview_state(preview_token=None):
    prune_ai_preview_cache()
    preview_token = preview_token or request.values.get('preview_token') or session.get('ai_preview_token')
    if not preview_token:
        return None, None

    cache_entry = AI_PREVIEW_CACHE.get(preview_token)
    if not cache_entry:
        return None, preview_token

    return cache_entry.get('state'), preview_token

def get_groq_api_key():
    return (
        os.getenv('GROQ_API_KEY')
        or os.getenv('GROQ_KEY')
    )

def get_quiz_details(quiz_id):
    if not quiz_id:
        return {}

    conn = get_db_connection()
    if not conn:
        return {}

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT title, year, batch, department, section, start_time FROM Quizzes WHERE quiz_id=%s",
                (quiz_id,)
            )
            quiz = cursor.fetchone()
    finally:
        conn.close()

    if not quiz:
        return {}

    timing = ''
    start_time = quiz.get('start_time')
    if start_time:
        if isinstance(start_time, str):
            timing = start_time
        else:
            timing = start_time.strftime('%d %b %I:%M %p')

    return {
        'title': quiz.get('title') or 'General Quiz',
        'year': quiz.get('year') or 'Any',
        'batch': quiz.get('batch') or 'General',
        'department': quiz.get('department') or '',
        'section': quiz.get('section') or '',
        'timing': timing,
    }

def get_quiz_modules(quiz_id):
    if not quiz_id:
        return []

    conn = get_db_connection()
    if not conn:
        return []

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT module
                FROM Questions
                WHERE quiz_id=%s AND module IS NOT NULL AND module != ''
                ORDER BY module
                """,
                (quiz_id,)
            )
            rows = cursor.fetchall()
    finally:
        conn.close()

    modules = [row.get('module', '').strip() for row in rows if row.get('module')]
    return [module for module in modules if module]

def get_difficulty_guidance(difficulty):
    normalized = (difficulty or 'Medium').strip().lower()
    guidance = {
        'easy': (
            "Keep questions straightforward, definition-based, and suitable for basic recall "
            "or direct understanding with simple distractors."
        ),
        'medium': (
            "Keep questions conceptual and application-oriented with moderate reasoning and "
            "plausible distractors."
        ),
        'hard': (
            "Keep questions analytical, scenario-based, or multi-step with close distractors "
            "that test deeper understanding."
        ),
    }
    return guidance.get(normalized, guidance['medium'])

def build_generation_brief(quiz_details, topic, difficulty, count):
    title = quiz_details.get('title') or 'General Quiz'
    year = quiz_details.get('year') or 'Any'
    prompt_text = topic or title

    lines = [
        "Use this exact generation input:",
        f"Year/Sem: {year}",
        f"Session Title: {title}",
        f"Prompt: {prompt_text}",
        f"No. of Questions: {count}",
        f"Difficulty: {difficulty}",
    ]
    return "\n".join(lines)

def parse_json_from_ai_response(content):
    if isinstance(content, list):
        content = ''.join(
            part.get('text', '') if isinstance(part, dict) else str(part)
            for part in content
        )

    cleaned = str(content or "").strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*```$', '', cleaned)

    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char not in '[{':
            continue
        try:
            parsed, _ = decoder.raw_decode(cleaned[index:])
            return parsed
        except json.JSONDecodeError:
            continue

    raise ValueError("AI returned invalid JSON.")

def normalize_generated_question(payload):
    if not isinstance(payload, dict):
        raise ValueError("Generated question payload is not an object.")

    question_text = (payload.get('question') or payload.get('question_text') or '').strip()
    options = {
        'a': str(payload.get('a') or payload.get('option_a') or '').strip(),
        'b': str(payload.get('b') or payload.get('option_b') or '').strip(),
        'c': str(payload.get('c') or payload.get('option_c') or '').strip(),
        'd': str(payload.get('d') or payload.get('option_d') or '').strip(),
    }

    correct = str(payload.get('correct') or payload.get('correct_option') or '').strip().upper()
    if correct in {'1', '2', '3', '4'}:
        correct = {'1': 'A', '2': 'B', '3': 'C', '4': 'D'}[correct]

    try:
        marks = int(payload.get('marks', 1))
    except (TypeError, ValueError):
        marks = 1

    if not question_text or not all(options.values()) or correct not in {'A', 'B', 'C', 'D'}:
        raise ValueError("Generated question is missing required fields.")

    return {
        'question': question_text,
        'a': options['a'],
        'b': options['b'],
        'c': options['c'],
        'd': options['d'],
        'correct': correct,
        'marks': max(1, marks)
    }

def question_fingerprint(question):
    text = question.get('question', '').lower().strip()
    text = re.sub(r'^\s*\d+[\).\s-]+', '', text)
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()

def is_duplicate_question(candidate, existing_fingerprints):
    candidate_fp = question_fingerprint(candidate)
    for existing_fp in existing_fingerprints:
        if candidate_fp == existing_fp:
            return True
        if candidate_fp in existing_fp or existing_fp in candidate_fp:
            return True
        if SequenceMatcher(None, candidate_fp, existing_fp).ratio() >= 0.88:
            return True
    return False

def get_generation_token_limit(count):
    count = max(1, count)
    return 170 if count <= 1 else min(180 + ((count - 1) * 95), 700)

def get_groq_retry_delay(response, error_message):
    retry_after = response.headers.get('Retry-After')
    if retry_after:
        try:
            return max(float(retry_after), 1.0)
        except ValueError:
            pass

    match = re.search(r'try again in\s+([0-9.]+)s', str(error_message), re.IGNORECASE)
    if match:
        try:
            return max(float(match.group(1)), 1.0)
        except ValueError:
            pass

    return 2.0

def estimate_prompt_tokens(messages):
    total_chars = sum(len(message.get('content', '')) for message in messages)
    return max(1, total_chars // 4)

def wait_for_groq_slot(messages, max_tokens):
    global GROQ_NEXT_ALLOWED_AT
    estimated_total_tokens = estimate_prompt_tokens(messages) + max_tokens
    cooldown_seconds = max(0.3, estimated_total_tokens / 450.0)

    with GROQ_REQUEST_LOCK:
        now = time.time()
        if GROQ_NEXT_ALLOWED_AT > now:
            time.sleep(GROQ_NEXT_ALLOWED_AT - now)
        GROQ_NEXT_ALLOWED_AT = time.time() + cooldown_seconds

def build_groq_messages(
    quiz_details,
    topic,
    difficulty,
    total_count,
    response_count=None,
    single_question=False,
    avoid_questions=None,
    question_number=None,
):
    generation_brief = build_generation_brief(quiz_details, topic, difficulty, total_count)
    difficulty_guidance = get_difficulty_guidance(difficulty)
    response_count = response_count or (1 if single_question else total_count)
    system_prompt = (
        "You are an expert exam question generator. "
        "Return only valid JSON. Do not include markdown, explanations, or code fences."
    )

    if single_question:
        user_prompt = (
            f"{generation_brief}\n"
            "The Prompt field is required. Follow the entered prompt exactly.\n"
            f"Difficulty Guidance: {difficulty_guidance}\n"
            f"Generate exactly 1 MCQ as question {question_number or 1} of {total_count}. "
            "Make it different from the others in concept and wording. "
            "Keep it concise and academically accurate. "
            "Return a JSON object with exactly these keys: question, a, b, c, d, correct, marks."
        )
    else:
        user_prompt = (
            f"{generation_brief}\n"
            "The Prompt field is required. Follow the entered prompt exactly.\n"
            f"Difficulty Guidance: {difficulty_guidance}\n"
            f"The requested total question count is {total_count}. "
            f"In this response, generate exactly {response_count} different MCQs. "
            "Do not repeat stems, ideas, or option sets. "
            "Keep them concise, accurate, and aligned to the session title, prompt, difficulty, and year/semester. "
            "Return a JSON object with one top-level key named questions. "
            "The questions value must be an array where every item has exactly these keys: "
            "question, a, b, c, d, correct, marks."
        )

    if avoid_questions:
        user_prompt += "\nDo not repeat or closely paraphrase these existing questions:\n"
        user_prompt += "\n".join(f"- {item}" for item in avoid_questions[:10])

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

def call_groq_chat(messages, max_tokens=400, json_mode=False):
    api_key = get_groq_api_key()
    if not api_key:
        raise RuntimeError("Missing GROQ_API_KEY in .env.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_error = None

    for model_name in dict.fromkeys(GROQ_FALLBACK_MODELS):
        for attempt in range(4):
            payload = {
                "model": model_name,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.2,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            try:
                wait_for_groq_slot(messages, max_tokens)
                response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=30)
            except requests.RequestException as e:
                last_error = RuntimeError(f"Groq request failed for model '{model_name}': {e}")
                if attempt < 3:
                    time.sleep(1.0 + attempt)
                    continue
                break

            if not response.ok:
                try:
                    error_payload = response.json()
                    error_message = error_payload.get('error', {}).get('message') or error_payload.get('message') or response.text
                except ValueError:
                    error_message = response.text

                if response.status_code == 429 and attempt < 3:
                    time.sleep(get_groq_retry_delay(response, error_message) + (attempt * 0.5))
                    continue

                last_error = RuntimeError(f"Groq API error ({response.status_code}) for model '{model_name}': {error_message}")
                break

            data = response.json()
            choices = data.get('choices') or []
            if not choices:
                last_error = RuntimeError(f"Groq returned no choices for model '{model_name}'.")
                break

            message = choices[0].get('message') or {}
            content = message.get('content')
            if not content:
                last_error = RuntimeError(f"Groq returned an empty response for model '{model_name}'.")
                break

            return content

    if last_error:
        raise last_error
    raise RuntimeError("Groq AI request failed.")

def parse_generated_questions_payload(parsed):
    if isinstance(parsed, dict) and 'questions' in parsed:
        parsed = parsed.get('questions')
    elif isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError("AI returned an invalid questions payload.")

    questions = [normalize_generated_question(item) for item in parsed]
    if not questions:
        raise ValueError("AI returned no valid questions.")
    return questions

def generate_batch_ai_questions_once(topic, difficulty, count, quiz_details=None, avoid_questions=None, total_count=None):
    quiz_details = quiz_details or {}
    total_count = total_count or count
    token_limit = get_generation_token_limit(count)
    messages = build_groq_messages(
        quiz_details,
        topic,
        difficulty,
        total_count,
        response_count=count,
        single_question=False,
        avoid_questions=avoid_questions,
    )

    try:
        content = call_groq_chat(messages, max_tokens=token_limit, json_mode=True)
        parsed = parse_json_from_ai_response(content)
    except Exception:
        fallback_messages = build_groq_messages(
            quiz_details,
            topic,
            difficulty,
            total_count,
            response_count=count,
            single_question=False,
            avoid_questions=avoid_questions,
        )
        fallback_messages[-1]["content"] += (
            " Example format: "
            "{\"questions\":[{\"question\":\"...\",\"a\":\"...\",\"b\":\"...\",\"c\":\"...\",\"d\":\"...\",\"correct\":\"A\",\"marks\":1}]}"
        )
        content = call_groq_chat(fallback_messages, max_tokens=token_limit, json_mode=False)
        parsed = parse_json_from_ai_response(content)

    return parse_generated_questions_payload(parsed)[:count]

def generate_single_ai_question(
    topic,
    difficulty,
    quiz_details=None,
    total_count=1,
    avoid_questions=None,
    question_number=None,
):
    quiz_details = quiz_details or {}
    token_limit = get_generation_token_limit(1)
    messages = build_groq_messages(
        quiz_details,
        topic,
        difficulty,
        total_count,
        single_question=True,
        avoid_questions=avoid_questions,
        question_number=question_number,
    )

    try:
        content = call_groq_chat(messages, max_tokens=token_limit, json_mode=True)
        parsed = parse_json_from_ai_response(content)
    except Exception:
        fallback_messages = build_groq_messages(
            quiz_details,
            topic,
            difficulty,
            total_count,
            single_question=True,
            avoid_questions=avoid_questions,
            question_number=question_number,
        )
        fallback_messages[-1]["content"] += (
            " Example format: "
            "{\"question\":\"...\",\"a\":\"...\",\"b\":\"...\",\"c\":\"...\",\"d\":\"...\",\"correct\":\"A\",\"marks\":1}"
        )
        content = call_groq_chat(fallback_messages, max_tokens=token_limit, json_mode=False)
        parsed = parse_json_from_ai_response(content)

    return parse_generated_questions_payload(parsed)[0]

def generate_ai_questions(topic, difficulty, count, quiz_details=None):
    quiz_details = quiz_details or {}
    count = min(max(int(count or 1), 1), MAX_AI_QUESTION_COUNT)
    questions = []
    seen = []

    def add_question(candidate):
        if is_duplicate_question(candidate, seen):
            return False
        seen.append(question_fingerprint(candidate))
        questions.append(candidate)
        return True

    batch_attempts = 0
    while len(questions) < count and batch_attempts < max(3, count * 2):
        remaining = count - len(questions)
        if remaining <= 1:
            break

        batch_attempts += 1
        batch_size = min(AI_BATCH_CHUNK_SIZE, remaining)

        try:
            batch_questions = generate_batch_ai_questions_once(
                topic,
                difficulty,
                batch_size,
                quiz_details=quiz_details,
                avoid_questions=[item['question'] for item in questions],
                total_count=count,
            )
        except Exception:
            time.sleep(0.8)
            continue

        added_any = False
        for candidate in batch_questions:
            if add_question(candidate):
                added_any = True

        if not added_any:
            time.sleep(0.5)

    refill_attempts = 0
    while len(questions) < count and refill_attempts < (count * 8):
        refill_attempts += 1
        try:
            candidate = generate_single_ai_question(
                topic,
                difficulty,
                quiz_details,
                total_count=count,
                avoid_questions=[item['question'] for item in questions],
                question_number=len(questions) + 1,
            )
        except Exception:
            time.sleep(1.0)
            continue

        if add_question(candidate):
            continue

        time.sleep(0.4)

    if len(questions) < count:
        raise ValueError(f"AI generated only {len(questions)} of {count} requested questions.")

    return questions[:count]

def render_ai_preview_page(preview_state, preview_token=None):
    quiz_id = preview_state.get('quiz_id')
    try:
        existing_modules = get_quiz_modules(quiz_id) if quiz_id else []
    except Exception:
        existing_modules = preview_state.get('existing_modules') or []

    from flask import render_template
    return render_template(
        'ai_preview.html',
        questions=preview_state.get('questions') or [],
        quiz_id=quiz_id,
        generation_context=preview_state.get('generation_context') or {},
        generation_prompt=preview_state.get('generation_prompt') or '',
        existing_modules=existing_modules,
        selected_batch=preview_state.get('selected_batch', ''),
        selected_session=preview_state.get('selected_session', ''),
        selected_branch=preview_state.get('selected_branch', ''),
        selected_timing=preview_state.get('selected_timing', ''),
        preview_token=preview_token or session.get('ai_preview_token', '')
    )

def collect_selected_ai_preview_rows(form):
    row_uids = form.getlist('row_uid')
    selected_row_ids = set(form.getlist('selected_row_ids'))
    q_texts = form.getlist('question_text')
    opt_as = form.getlist('option_a')
    opt_bs = form.getlist('option_b')
    opt_cs = form.getlist('option_c')
    opt_ds = form.getlist('option_d')
    corrects = form.getlist('correct_option')
    marks = form.getlist('marks')

    rows = []
    packed_rows = zip(row_uids, q_texts, opt_as, opt_bs, opt_cs, opt_ds, corrects, marks)
    for row_uid, q_text, opt_a, opt_b, opt_c, opt_d, correct, mark in packed_rows:
        if row_uid not in selected_row_ids:
            continue
        rows.append({
            'serial_no': len(rows) + 1,
            'question_text': (q_text or '').strip(),
            'option_a': (opt_a or '').strip(),
            'option_b': (opt_b or '').strip(),
            'option_c': (opt_c or '').strip(),
            'option_d': (opt_d or '').strip(),
            'correct_option': (correct or 'A').strip().upper() or 'A',
            'marks': int(mark or 1),
        })

    return rows

def format_test_case_block(cases):
    if not cases:
        return ''
    return '\n---\n'.join([str(c or '').strip() for c in cases])

def split_test_case_block(raw_value):
    text = (raw_value or '').strip()
    if not text:
        return []

    parts = [part.strip() for part in TEST_CASE_SEPARATOR.split(text) if part.strip()]
    return parts or [text]

def normalize_judge_output(raw_value):
    lines = [line.rstrip() for line in str(raw_value or '').strip().splitlines()]
    return '\n'.join(lines).strip()

def build_student_query(args):
    query = 'SELECT * FROM Users WHERE role = %s'
    params = ['Student']
    
    batch = args.get('batch', '')
    year = args.get('year', '')
    department = args.get('department', '')
    search = args.get('search', '')
    
    if batch:
        query += ' AND enrolled_session = %s'
        params.append(batch)
    if year:
        query += ' AND batch_year = %s'
        params.append(year)
    if department:
        query += ' AND department = %s'
        params.append(department)
    if search:
        query += ' AND (full_name ILIKE %s OR email ILIKE %s)'
        params.extend([f'%{search}%', f'%{search}%'])
    
    query += ' ORDER BY user_id DESC'
    return query, params

def build_question_test_cases(question_row):
    inputs = split_test_case_block(question_row.get('test_input'))
    outputs = split_test_case_block(question_row.get('test_output'))

    if not inputs and not outputs:
        return []

    case_count = max(len(inputs), len(outputs))
    cases = []
    for index in range(case_count):
        cases.append({
            'input': inputs[index] if index < len(inputs) else '',
            'expected': outputs[index] if index < len(outputs) else '',
        })
    return cases

