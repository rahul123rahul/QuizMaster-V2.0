from flask import Blueprint, request, render_template, redirect, jsonify, session, flash, send_file, current_app, Response
from utils import get_db_connection, get_groq_api_key, call_groq_chat, build_groq_messages
import os
import hashlib
import json
import secrets
import re
import io
import csv
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = 'static/uploads/study_materials'
MAX_FILE_SIZE = 1024 * 1024 * 1024  # 1GB max

# Expanded file type support
ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx',
    'txt', 'rtf', 'odt', 'odp', 'ods',
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg',
    'mp4', 'avi', 'mov', 'mkv', 'webm',
    'mp3', 'wav', 'ogg', 'flac',
    'zip', 'rar', '7z', 'tar', 'gz'
}
ALLOWED_MIME_TYPES = {
    'application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'image/jpeg', 'image/png', 'image/gif', 'image/bmp', 'image/webp',
    'video/mp4', 'video/avi', 'video/quicktime', 'video/webm',
    'audio/mpeg', 'audio/wav', 'audio/ogg',
    'application/zip', 'application/x-rar-compressed', 'application/x-7z-compressed'
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_file(file, max_size=MAX_FILE_SIZE):
    """Validate file type, size, and content"""
    if not file or not file.filename:
        return False, "No file provided"
    
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"File type .{ext} not allowed"
    
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    
    if size > max_size:
        return False, f"File size {size/(1024*1024):.1f}MB exceeds {max_size/(1024*1024):.0f}MB limit"
    
    return True, None

def calculate_checksum(file):
    """Calculate SHA256 checksum of file"""
    file.seek(0)
    checksum = hashlib.sha256(file.read()).hexdigest()
    file.seek(0)
    return checksum

def get_mime_type(filename):
    """Get MIME type from filename"""
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    mime_map = {
        'pdf': 'application/pdf', 'doc': 'application/msword', 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'ppt': 'application/vnd.ms-powerpoint', 'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'xls': 'application/vnd.ms-excel', 'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif', 'webp': 'image/webp',
        'mp4': 'video/mp4', 'avi': 'video/avi', 'mov': 'video/quicktime', 'webm': 'video/webm',
        'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg',
        'zip': 'application/zip', 'rar': 'application/x-rar-compressed', '7z': 'application/x-7z-compressed'
    }
    return mime_map.get(ext, 'application/octet-stream')

def generate_ai_tags(content, title):
    """Generate AI-powered tags using existing Groq API"""
    if not content and not title:
        return []
    
    prompt = f"""Analyze this study material:
Title: {title}
Content: {str(content)[:2000]}

Generate 5-10 relevant tags in JSON array format. Include:
- Subject/topic keywords
- Difficulty indicators
- Learning objectives
- Related concepts
Return ONLY a JSON array of strings, no other text."""

    try:
        messages = [
            {"role": "system", "content": "You are an educational content analyzer. Generate relevant tags for study materials."},
            {"role": "user", "content": prompt}
        ]
        result = call_groq_chat(messages, max_tokens=200, json_mode=True)
        
        # Parse JSON array from response
        tags = re.findall(r'\[([^\]]+)\]', result)
        if tags:
            import ast
            try:
                return ast.literal_eval('[' + tags[0] + ']')
            except:
                pass
        
        # Fallback: extract keywords
        keywords = re.findall(r'"([^"]+)"', result)
        return keywords[:8] if keywords else []
    except Exception as e:
        return []

study_bp = Blueprint('study', __name__, template_folder='../templates')

@study_bp.route('/admin/study/')
@study_bp.route('/admin/study')
def admin_study():
    if session.get('role') != 'Admin': return redirect('/')
    conn = get_db_connection()
    subjects = []; chapters = []; topics = []; materials = []; batches = []
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM StudySubjects ORDER BY name')
                subjects = cursor.fetchall()
                cursor.execute('SELECT sc.id, sc.name, ss.name as subject_name FROM StudyChapters sc JOIN StudySubjects ss ON sc.subject_id = ss.id ORDER BY sc.name')
                chapters = cursor.fetchall()
                cursor.execute('SELECT st.id, st.name, sc.name as chapter_name FROM StudyTopics st JOIN StudyChapters sc ON st.chapter_id = sc.id ORDER BY st.name')
                topics = cursor.fetchall()
                cursor.execute('''
                    SELECT sm.*, st.name as topic_name 
                    FROM StudyMaterials sm 
                    LEFT JOIN StudyTopics st ON sm.topic_id = st.id 
                    ORDER BY sm.created_at DESC
                ''')
                materials = cursor.fetchall()
                cursor.execute("SELECT DISTINCT enrolled_session FROM Users WHERE enrolled_session IS NOT NULL AND enrolled_session != ''")
                batches = cursor.fetchall()
        finally:
            conn.close()
    return render_template('study_materials.html', 
                          subjects=subjects, chapters=chapters, topics=topics, 
                          materials=materials, batches=batches, role='Admin')

@study_bp.route('/student/study/')
@study_bp.route('/student/study')
def student_study():
    if session.get('role') != 'Student': return redirect('/')
    conn = get_db_connection()
    subjects = []; materials = []; topics = []; chapters = []; batches = []; filter_types = []; filter_difficulties = []; total_materials = 0
    user_batch = session.get('enrolled_session', '')
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM StudySubjects ORDER BY name')
                subjects = cursor.fetchall()
                
                cursor.execute('SELECT sc.id, sc.name, ss.name as subject_name FROM StudyChapters sc JOIN StudySubjects ss ON sc.subject_id = ss.id ORDER BY sc.name')
                chapters = cursor.fetchall()
                
                cursor.execute('SELECT st.id, st.name, sc.name as chapter_name FROM StudyTopics st JOIN StudyChapters sc ON st.chapter_id = sc.id ORDER BY st.name')
                topics = cursor.fetchall()
                
                cursor.execute('''
                    SELECT sm.*, st.name as topic_name, sc.name as chapter_name, ss.name as subject_name
                    FROM StudyMaterials sm
                    LEFT JOIN StudyTopics st ON sm.topic_id = st.id
                    LEFT JOIN StudyChapters sc ON st.chapter_id = sc.id
                    LEFT JOIN StudySubjects ss ON sc.subject_id = ss.id
                    WHERE sm.is_public = 1 OR JSON_EXTRACT(sm.batch_assignment, %s) = 1
                    ORDER BY sm.created_at DESC
                    LIMIT 30
                ''', (f'$.{user_batch}' if user_batch else '$."All"'))
                materials = cursor.fetchall()
                
                cursor.execute("SELECT DISTINCT type FROM StudyMaterials WHERE type IS NOT NULL")
                filter_types = [t['type'] for t in cursor.fetchall()]
                
                try:
                    cursor.execute("SELECT DISTINCT difficulty FROM StudyMaterials WHERE difficulty IS NOT NULL")
                    filter_difficulties = [d['difficulty'] for d in cursor.fetchall()]
                except:
                    filter_difficulties = []
                
                cursor.execute("SELECT COUNT(*) as total FROM StudyMaterials WHERE is_public = 1 OR JSON_EXTRACT(batch_assignment, %s) = 1", 
                             (f'$.{user_batch}' if user_batch else '$."All"'))
                total_materials = cursor.fetchone()['total']
        finally:
            conn.close()
    
    # Calculate computed semester
    def calc_sem(sem):
        if sem: return sem
        month = datetime.now().month
        return 'I' if 6 <= month <= 11 else 'II'
    
    return render_template('student_study.html', 
                          subjects=subjects, materials=materials, 
                          topics=topics, chapters=chapters, batches=batches, 
                          filter_types=filter_types, filter_difficulties=filter_difficulties,
                          total_materials=total_materials, role='Student',
                          user_full_name=session.get('full_name', 'Student'),
                          user_email=session.get('email'),
                          user_department=session.get('department'),
                          user_study_year=session.get('study_year'),
                          user_semester=session.get('semester'),
                          user_profile_image=session.get('avatar'),
                          computed_semester=calc_sem(session.get('semester')))

@study_bp.route('/coordinator/study/')
@study_bp.route('/coordinator/study')
def coordinator_study():
    if session.get('role') != 'Coordinator': return redirect('/')
    conn = get_db_connection()
    subjects = []; chapters = []; topics = []; materials = []; batches = []
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT * FROM StudySubjects ORDER BY name')
                subjects = cursor.fetchall()
                cursor.execute('SELECT sc.id, sc.name, ss.name as subject_name FROM StudyChapters sc JOIN StudySubjects ss ON sc.subject_id = ss.id ORDER BY sc.name')
                chapters = cursor.fetchall()
                cursor.execute('SELECT st.id, st.name, sc.name as chapter_name FROM StudyTopics st JOIN StudyChapters sc ON st.chapter_id = sc.id ORDER BY st.name')
                topics = cursor.fetchall()
                cursor.execute('''
                    SELECT sm.*, st.name as topic_name 
                    FROM StudyMaterials sm 
                    LEFT JOIN StudyTopics st ON sm.topic_id = st.id 
                    ORDER BY sm.created_at DESC
                ''')
                materials = cursor.fetchall()
                cursor.execute("SELECT DISTINCT enrolled_session FROM Users WHERE enrolled_session IS NOT NULL AND enrolled_session != ''")
                batches = cursor.fetchall()
        finally:
            conn.close()
    return render_template('study_materials.html', 
                          subjects=subjects, chapters=chapters, topics=topics, 
                          materials=materials, batches=batches, role='Coordinator')

# AJAX APIs for dynamic operations
@study_bp.route('/api/study/subjects', methods=['GET'])
def api_subjects():
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, name FROM StudySubjects")
                subjects = cursor.fetchall()
                return jsonify(subjects)
        finally:
            conn.close()
    return jsonify([])

@study_bp.route('/study/download/<int:material_id>')
def download_material(material_id):
    conn = get_db_connection()
    material = None
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM StudyMaterials WHERE id=%s", (material_id,))
                material = cursor.fetchone()
                
                if material:
                    cursor.execute("UPDATE StudyMaterials SET download_count = download_count + 1 WHERE id = %s", (material_id,))
                    
                    today = datetime.now().date()
                    cursor.execute("""
                        INSERT INTO StudyMaterialStats (material_id, date, downloads)
                        VALUES (%s, %s, 1)
                        ON DUPLICATE KEY UPDATE downloads = downloads + 1
                    """, (material_id, today))
            conn.commit()
        finally:
            conn.close()
    
    if not material or not material.get('file_path'):
        flash('File not found')
        return redirect('/student/study')
    
    file_path = material['file_path']
    if not file_path.startswith('static/') and not file_path.startswith('/'):
        file_path = 'static/' + file_path
    
    if not os.path.exists(file_path):
        flash('File not found: ' + file_path)
        return redirect('/student/study')
    
    return send_file(file_path, as_attachment=True, download_name=material.get('original_filename', 'material'))

# Track views with analytics
@study_bp.route('/study/view/<int:material_id>')
def track_view(material_id):
    conn = get_db_connection()
    today = datetime.now().date()
    
    if conn:
        try:
            with conn.cursor() as cursor:
                # Track view
                if session.get('user_id'):
                    cursor.execute("INSERT IGNORE INTO StudyMaterialViews (material_id, user_id) VALUES (%s, %s)", (material_id, session['user_id']))
                
                # Increment view count
                cursor.execute("UPDATE StudyMaterials SET view_count = view_count + 1 WHERE id=%s", (material_id,))
                
                # Update daily stats
                cursor.execute("""
                    INSERT INTO StudyMaterialStats (material_id, date, views, unique_viewers)
                    VALUES (%s, %s, 1, %s)
                    ON DUPLICATE KEY UPDATE views = views + 1, 
                    unique_viewers = unique_viewers + %s
                """, (material_id, today, 1 if session.get('user_id') else 0, 1 if session.get('user_id') else 0))
            conn.commit()
        finally:
            conn.close()
    return redirect(f'/student/study#material-{material_id}')

# --- ENHANCED: SEARCH AND DISCOVERY ---
@study_bp.route('/api/study/search', methods=['GET'])
def search_materials():
    query = request.args.get('q', '').strip()
    filters = {
        'type': request.args.get('type'),
        'difficulty': request.args.get('difficulty'),
        'subject': request.args.get('subject'),
        'chapter': request.args.get('chapter'),
        'topic': request.args.get('topic'),
        'sort': request.args.get('sort', 'recent'),
        'limit': min(int(request.args.get('limit', 20)), 100),
        'offset': int(request.args.get('offset', 0))
    }
    
    # For students: only public materials
    role = session.get('role')
    user_batch = session.get('enrolled_session', '')
    
    sql_parts = ["""
        SELECT sm.*, st.name as topic_name, sc.name as chapter_name, ss.name as subject_name
        FROM StudyMaterials sm
        LEFT JOIN StudyTopics st ON sm.topic_id = st.id
        LEFT JOIN StudyChapters sc ON st.chapter_id = sc.id
        LEFT JOIN StudySubjects ss ON sc.subject_id = ss.id
        WHERE 1=1
    """]
    params = []
    
    if role == 'Student':
        sql_parts.append(" AND (sm.is_public = 1 OR JSON_EXTRACT(sm.batch_assignment, %s) = 1)")
        params.append(f'$.{user_batch}' if user_batch else '$."All"')
    
    if query:
        sql_parts.append(" AND (sm.title LIKE %s OR sm.description LIKE %s OR sm.tags LIKE %s)")
        term = f'%{query}%'
        params.extend([term, term, term])
    
    if filters['type']:
        sql_parts.append(" AND sm.type = %s")
        params.append(filters['type'])
    
    if filters['difficulty']:
        sql_parts.append(" AND sm.difficulty = %s")
        params.append(filters['difficulty'])
    
    if filters['subject']:
        sql_parts.append(" AND ss.name = %s")
        params.append(filters['subject'])
    
    # Sorting
    sort_map = {
        'recent': 'sm.created_at DESC',
        'popular': 'sm.view_count DESC',
        'rated': 'sm.rating DESC',
        'title': 'sm.title ASC'
    }
    sql_parts.append(f" ORDER BY {sort_map.get(filters['sort'], sort_map['recent'])}")
    
    sql_parts.append(" LIMIT %s OFFSET %s")
    params.extend([filters['limit'], filters['offset']])
    
    conn = get_db_connection()
    results = []
    total_count = 0
    
    if conn:
        try:
            with conn.cursor() as cursor:
                # Get total count
                count_sql = ' '.join(sql_parts[:sql_parts.index('ORDER BY')]) if 'ORDER BY' in sql_parts else ' '.join(sql_parts).replace('LIMIT %s OFFSET %s', '')
                cursor.execute('SELECT COUNT(*) as c FROM (' + count_sql + ') as t', tuple(params[:-2]))
                total_count = cursor.fetchone()['c']
                
                # Get results
                cursor.execute(' '.join(sql_parts), tuple(params))
                results = cursor.fetchall()
        finally:
            conn.close()
    
    return jsonify({
        'results': results,
        'total': total_count,
        'query': query,
        'filters': filters
    })

# --- STUDENT STUDY MATERIALS PAGINATED API ---
@study_bp.route('/api/study/materials/paginated', methods=['GET'])
def get_student_materials_paginated():
    try:
        page = int(request.args.get('page', 1))
        per_page = 30
        
        search = request.args.get('search', '').strip()
        filters = {
            'type': request.args.get('type'),
            'difficulty': request.args.get('difficulty'),
            'subject': request.args.get('subject'),
            'chapter': request.args.get('chapter'),
            'topic': request.args.get('topic'),
            'sort': request.args.get('sort', 'recent')
        }
        
        role = session.get('role')
        if role != 'Student':
            return jsonify({'error': 'Unauthorized'}), 403
        
        user_batch = session.get('enrolled_session', '')
        
        # Build WHERE clause safely
        where_clauses = ["(sm.is_public = 1 OR JSON_EXTRACT(sm.batch_assignment, %s) = 1)"]
        params = [f'$.{user_batch}' if user_batch else '$."All"']
        
        if search:
            where_clauses.append(" (sm.title LIKE %s OR sm.description LIKE %s OR sm.tags LIKE %s)")
            term = f'%{search}%'
            params.extend([term, term, term])
        
        if filters.get('type'):
            where_clauses.append(" sm.type = %s")
            params.append(filters['type'])
        
        if filters.get('difficulty'):
            where_clauses.append(" sm.difficulty = %s")
            params.append(filters['difficulty'])
        
        if filters.get('subject'):
            where_clauses.append(" ss.name = %s")
            params.append(filters['subject'])
        
        # Build full SQL
        base_sql = "SELECT sm.*, st.name as topic_name, sc.name as chapter_name, ss.name as subject_name FROM StudyMaterials sm LEFT JOIN StudyTopics st ON sm.topic_id = st.id LEFT JOIN StudyChapters sc ON st.chapter_id = sc.id LEFT JOIN StudySubjects ss ON sc.subject_id = ss.id WHERE " + " AND ".join(where_clauses)
        
        # Get total count
        count_sql = "SELECT COUNT(*) as c FROM (" + base_sql + ") as subq"
        
        sort_map = {
            'recent': 'sm.created_at DESC',
            'popular': 'sm.view_count DESC',
            'rated': 'sm.rating DESC',
            'title': 'sm.title ASC'
        }
        order_by = sort_map.get(filters.get('sort', 'recent'), sort_map['recent'])
        full_sql = base_sql + " ORDER BY " + order_by + " LIMIT %s OFFSET %s"
        
        conn = get_db_connection()
        results = []
        total_count = 0
        
        if conn:
            try:
                with conn.cursor() as cursor:
                    try:
                        cursor.execute(count_sql, tuple(params))
                        total_count = cursor.fetchone()['c']
                    except Exception as e:
                        print(f"Count SQL error: {e}")
                        total_count = 0
                    
                    offset = (page - 1) * per_page
                    query_params = tuple(params + [per_page, offset])
                    
                    try:
                        cursor.execute(full_sql, query_params)
                        results = cursor.fetchall()
                    except Exception as e:
                        print(f"Main SQL error: {e}")
                        results = []
                    
                    # Get filter options
                    subjects = []
                    chapters = []
                    types = []
                    difficulties = []
                    
                    try:
                        cursor.execute("SELECT DISTINCT name as subject FROM StudySubjects ORDER BY name")
                        subjects = cursor.fetchall()
                    except: pass
                    
                    try:
                        cursor.execute("SELECT DISTINCT name as chapter, subject_id FROM StudyChapters ORDER BY name")
                        chapters = cursor.fetchall()
                    except: pass
                    
                    try:
                        cursor.execute("SELECT DISTINCT type FROM StudyMaterials WHERE type IS NOT NULL")
                        types = cursor.fetchall()
                    except: pass
                    
                    try:
                        cursor.execute("SELECT DISTINCT difficulty FROM StudyMaterials WHERE difficulty IS NOT NULL")
                        difficulties = cursor.fetchall()
                    except: pass
            except Exception as e:
                print(f"API Error: {e}")
            finally:
                conn.close()
        
        total_pages = (total_count + per_page - 1) // per_page if per_page > 0 else 0
        
        return jsonify({
            'results': results,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total_count,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1,
                'next_page': page + 1 if page < total_pages else None,
                'prev_page': page - 1 if page > 1 else None
            },
            'filters': filters,
            'options': {
                'subjects': [s.get('subject', '') for s in subjects if s.get('subject')],
                'chapters': [{'name': c.get('chapter', ''), 'subject_id': c.get('subject_id')} for c in chapters if c.get('chapter')],
                'types': [t.get('type', '') for t in types if t.get('type')],
                'difficulties': [d.get('difficulty', '') for d in difficulties if d.get('difficulty')]
            }
        })
    except Exception as e:
        print(f"Overall API error: {e}")
        return jsonify({'error': str(e), 'results': []}), 500

# --- GET FILTER OPTIONS ---
@study_bp.route('/api/study/filter-options', methods=['GET'])
def get_filter_options():
    conn = get_db_connection()
    options = {'subjects': [], 'chapters': [], 'types': [], 'difficulties': []}
    
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT DISTINCT name as subject FROM StudySubjects ORDER BY name")
                options['subjects'] = [s['subject'] for s in cursor.fetchall()]
                
                cursor.execute("SELECT DISTINCT name as chapter FROM StudyChapters ORDER BY name")
                options['chapters'] = [c['chapter'] for c in cursor.fetchall()]
                
                cursor.execute("SELECT DISTINCT type FROM StudyMaterials WHERE type IS NOT NULL")
                options['types'] = [t['type'] for t in cursor.fetchall()]
                
                try:
                    cursor.execute("SELECT DISTINCT difficulty FROM StudyMaterials WHERE difficulty IS NOT NULL")
                    options['difficulties'] = [d['difficulty'] for d in cursor.fetchall()]
                except:
                    options['difficulties'] = []
        finally:
            conn.close()
    
    return jsonify(options)

# --- ENHANCED: ANALYTICS DASHBOARD ---
@study_bp.route('/api/study/analytics/dashboard', methods=['GET'])
def analytics_dashboard():
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    days = min(int(request.args.get('days', 30)), 365)
    conn = get_db_connection()
    
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    data = {
        'overview': {},
        'trending': [],
        'by_type': [],
        'by_difficulty': [],
        'by_subject': [],
        'views_timeline': [],
        'top_materials': []
    }
    
    try:
        with conn.cursor() as cursor:
            # Overview stats
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_materials,
                    SUM(view_count) as total_views,
                    SUM(download_count) as total_downloads,
                    AVG(rating) as avg_rating
                FROM StudyMaterials
            """)
            data['overview'] = cursor.fetchone()
            
            # Trending (last 7 days)
            cursor.execute("""
                SELECT sm.id, sm.title, sm.type, SUM(sms.views) as views
                FROM StudyMaterials sm
                JOIN StudyMaterialStats sms ON sm.id = sms.material_id
                WHERE sms.date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                GROUP BY sm.id
                ORDER BY views DESC
                LIMIT 10
            """)
            data['trending'] = cursor.fetchall()
            
            # By type
            cursor.execute("""
                SELECT type, COUNT(*) as count, SUM(view_count) as views
                FROM StudyMaterials
                GROUP BY type
            """)
            data['by_type'] = cursor.fetchall()
            
            # By difficulty
            cursor.execute("""
                SELECT COALESCE(difficulty, 'intermediate') as difficulty, COUNT(*) as count
                FROM StudyMaterials
                GROUP BY difficulty
            """)
            data['by_difficulty'] = cursor.fetchall()
            
            # By subject
            cursor.execute("""
                SELECT ss.name as subject, COUNT(sm.id) as count, SUM(sm.view_count) as views
                FROM StudySubjects ss
                LEFT JOIN StudyChapters sc ON sc.subject_id = ss.id
                LEFT JOIN StudyTopics st ON st.chapter_id = sc.id
                LEFT JOIN StudyMaterials sm ON sm.topic_id = st.id
                GROUP BY ss.id
                ORDER BY count DESC
            """)
            data['by_subject'] = cursor.fetchall()
            
            # Views timeline
            cursor.execute("""
                SELECT date, SUM(views) as views, SUM(downloads) as downloads
                FROM StudyMaterialStats
                WHERE date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                GROUP BY date
                ORDER BY date
            """, (days,))
            data['views_timeline'] = cursor.fetchall()
            
            # Top materials
            cursor.execute("""
                SELECT id, title, type, view_count, download_count, rating
                FROM StudyMaterials
                ORDER BY view_count DESC
                LIMIT 10
            """)
            data['top_materials'] = cursor.fetchall()
    finally:
        conn.close()
    
    return jsonify(data)

# --- ENHANCED: ADVANCED FILE UPLOAD WITH AI TAGGING ---
@study_bp.route('/api/study/materials/upload', methods=['POST'])
def upload_material_advanced():
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Get form data
    topic_id = request.form.get('topic_id')
    title = request.form.get('title')
    mat_type = request.form.get('type', 'pdf')
    description = request.form.get('description', '')
    difficulty = request.form.get('difficulty', 'intermediate')
    duration = request.form.get('duration_minutes')
    is_public = 1 if request.form.get('is_public') == 'true' else 0
    is_featured = 1 if request.form.get('is_featured') == 'true' else 0
    generate_ai_tags_flag = request.form.get('ai_tags', 'true') == 'true'
    batch_assignment = request.form.get('batch_assignment', '')
    tags = request.form.get('tags', '')
    objectives = request.form.get('objectives', '')
    release_date = request.form.get('release_date') or None
    
    if not topic_id or not title:
        return jsonify({'error': 'Topic and title are required'}), 400
    
    # Handle JSON fields - validate and convert properly
    def safe_json(value):
        if not value:
            return None
        if isinstance(value, list):
            try:
                return json.dumps(value)
            except:
                return None
        try:
            json.loads(value)
            return value
        except:
            return None
    
    tags = safe_json(tags)
    objectives = safe_json(objectives)
    batch_assignment = safe_json(batch_assignment) if batch_assignment else '{}'
    
    # Handle file upload
    file = request.files.get('file')
    file_path = None
    file_size = 0
    checksum = None
    mime_type = None
    original_filename = None
    
    if file and file.filename:
        valid, error = validate_file(file)
        if not valid:
            return jsonify({'error': error}), 400
        
        # Save file
        original_filename = secure_filename(file.filename)
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}_{original_filename}"
        
        if not os.path.exists(UPLOAD_FOLDER):
            os.makedirs(UPLOAD_FOLDER)
        
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)
        file_size = os.path.getsize(file_path)
        
        # Calculate checksum
        with open(file_path, 'rb') as f:
            checksum = calculate_checksum(f)
        
        mime_type = get_mime_type(original_filename)
    
    # Generate AI tags if requested
    ai_tags = []
    if generate_ai_tags_flag and (description or file_path):
        try:
            ai_tags = generate_ai_tags(description, title)
        except Exception as e:
            print(f"AI tagging error: {e}")
            ai_tags = []
    
    # Get video URL if type is video
    video_url = request.form.get('video_url', '')
    if mat_type == 'video' and not file:
        video_url = request.form.get('video_url', '')
    
    # Insert into database
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                # Check if table exists
                cursor.execute("SHOW TABLES LIKE 'StudyMaterials'")
                if not cursor.fetchone():
                    return jsonify({'error': 'StudyMaterials table does not exist. Please initialize the database.'}), 500
                
                # Get column info to see what's available
                cursor.execute("DESCRIBE StudyMaterials")
                columns = [row['Field'] for row in cursor.fetchall()]
                print(f"Available columns: {columns}")
                
                ai_tags_json = json.dumps(ai_tags) if ai_tags else None
                
                # Build insert dynamically based on available columns
                insert_fields = ['topic_id', 'title', 'type', 'file_path', 'video_url', 'content', 
                               'file_size', 'mime_type', 'original_filename', 'checksum', 'description', 
                               'difficulty', 'duration_minutes', 'tags', 'ai_tags', 'objectives',
                               'batch_assignment', 'is_public', 'is_featured', 'release_date']
                
                insert_values = [topic_id, title, mat_type, file_path, video_url, '', file_size, mime_type, 
                             original_filename, checksum, description, difficulty, duration, tags, 
                             ai_tags_json, objectives, batch_assignment, is_public, is_featured, 
                             release_date]
                
                if 'created_by' in columns:
                    insert_fields.append('created_by')
                    insert_values.append(session.get('user_id'))
                
                placeholders = ', '.join(['%s'] * len(insert_values))
                fields_str = ', '.join(insert_fields)
                
                sql = f"INSERT INTO StudyMaterials ({fields_str}) VALUES ({placeholders})"
                cursor.execute(sql, tuple(insert_values))
                
                material_id = cursor.lastrowid
            conn.commit()
            return jsonify({
                'message': 'Material uploaded successfully',
                'id': material_id,
                'ai_tags': ai_tags,
                'checksum': checksum
            })
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"Upload error: {error_detail}")
            return jsonify({'error': f'Server error: {str(e)}'}), 500
        finally:
            conn.close()
    
    return jsonify({'error': 'Database error'}), 500

# --- RESUMABLE UPLOAD: INITIATE ---
@study_bp.route('/api/study/upload/init', methods=['POST'])
def init_resumable_upload():
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    filename = request.json.get('filename')
    total_chunks = request.json.get('total_chunks', 1)
    chunk_size = request.json.get('chunk_size')
    
    if not filename:
        return jsonify({'error': 'Filename required'}), 400
    
    # Generate unique upload ID
    upload_id = secrets.token_hex(16)
    
    # Validate extension
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'error': f'File type .{ext} not allowed'}), 400
    
    return jsonify({
        'upload_id': upload_id,
        'status': 'initiated'
    })

# --- RESUMABLE UPLOAD: CHUNK ---
@study_bp.route('/api/study/upload/chunk', methods=['POST'])
def upload_chunk():
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    upload_id = request.form.get('upload_id')
    chunk_number = int(request.form.get('chunk_number', 0))
    chunk = request.files.get('chunk')
    
    if not upload_id or not chunk:
        return jsonify({'error': 'Upload ID and chunk required'}), 400
    
    # Store chunk (in production, use Redis or file-based storage)
    chunk_data = chunk.read()
    
    # In production, we'd store this in Redis or file
    # For now, just acknowledge
    return jsonify({
        'upload_id': upload_id,
        'chunk': chunk_number,
        'received': len(chunk_data)
    })

# --- RESUMABLE UPLOAD: COMPLETE ---
@study_bp.route('/api/study/upload/complete', methods=['POST'])
def complete_resumable_upload():
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    upload_id = request.form.get('upload_id')
    topic_id = request.form.get('topic_id')
    title = request.form.get('title')
    
    # In production, we'd reconstruct the file from chunks
    # For now, return placeholder
    
    return jsonify({
        'message': 'Upload completed',
        'material_id': None  # Would be real ID after reconstruction
    })

# --- MATERIAL RATING ---
@study_bp.route('/api/study/materials/<int:material_id>/rate', methods=['POST'])
def rate_material(material_id):
    if not session.get('user_id'):
        return jsonify({'error': 'Login required'}), 401
    
    data = request.get_json(silent=True) or {}
    rating = int(data.get('rating', 0))
    if rating < 1 or rating > 5:
        return jsonify({'error': 'Rating must be 1-5'}), 400
    
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                # Check if already rated
                cursor.execute("""
                    SELECT id FROM StudyMaterialComments 
                    WHERE material_id = %s AND user_id = %s AND rating IS NOT NULL
                """, (material_id, session['user_id']))
                
                if cursor.fetchone():
                    # Update existing
                    cursor.execute("""
                        UPDATE StudyMaterialComments SET rating = %s 
                        WHERE material_id = %s AND user_id = %s
                    """, (rating, material_id, session['user_id']))
                else:
                    # Insert new
                    cursor.execute("""
                        INSERT INTO StudyMaterialComments (material_id, user_id, rating)
                        VALUES (%s, %s, %s)
                    """, (material_id, session['user_id'], rating))
                
                # Recalculate average
                cursor.execute("""
                    UPDATE StudyMaterials m SET
                        m.rating = (SELECT AVG(rating) FROM StudyMaterialComments WHERE material_id = %s AND rating IS NOT NULL),
                        m.rating_count = (SELECT COUNT(*) FROM StudyMaterialComments WHERE material_id = %s AND rating IS NOT NULL)
                    WHERE m.id = %s
                """, (material_id, material_id, material_id))
            conn.commit()
            return jsonify({'message': 'Rated successfully'})
        finally:
            conn.close()
    
    return jsonify({'error': 'Database error'}), 500

# --- MATERIAL BOOKMARK ---
@study_bp.route('/api/study/materials/<int:material_id>/bookmark', methods=['POST', 'DELETE'])
def bookmark_material(material_id):
    if not session.get('user_id'):
        return jsonify({'error': 'Login required'}), 401
    
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                if request.method == 'POST':
                    note = request.json.get('note', '')
                    cursor.execute("""
                        INSERT INTO StudyMaterialBookmarks (material_id, user_id, note)
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE note = %s
                    """, (material_id, session['user_id'], note, note))
                    message = 'Bookmarked'
                else:
                    cursor.execute("DELETE FROM StudyMaterialBookmarks WHERE material_id = %s AND user_id = %s",
                               (material_id, session['user_id']))
                    message = 'Bookmark removed'
            conn.commit()
            return jsonify({'message': message})
        finally:
            conn.close()
    
    return jsonify({'error': 'Database error'}), 500

# --- MATERIAL SHARE ---
@study_bp.route('/api/study/materials/<int:material_id>/share', methods=['POST'])
def share_material(material_id):
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'error': 'Unauthorized'}, 403)
    
    access_type = request.json.get('access_type', 'private')
    expires_at = request.json.get('expires_at')
    max_downloads = request.json.get('max_downloads')
    password = request.json.get('password')
    
    share_token = secrets.token_urlsafe(24)
    
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO StudyMaterialShares 
                    (material_id, share_token, access_type, expires_at, max_downloads, share_password, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (material_id, share_token, access_type, expires_at, max_downloads, password, session['user_id']))
            conn.commit()
            return jsonify({
                'message': 'Share link created',
                'share_url': f'/study/shared/{share_token}'
            })
        finally:
            conn.close()
    
    return jsonify({'error': 'Database error'}), 500

# --- GET SHARED MATERIAL ---
@study_bp.route('/study/shared/<token>')
def get_shared_material(token):
    conn = get_db_connection()
    material = None
    
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT sm.*, s.share_token, s.access_type, s.expires_at, s.max_downloads, s.download_count
                    FROM StudyMaterialShares s
                    JOIN StudyMaterials sm ON s.material_id = sm.id
                    WHERE s.share_token = %s
                """, (token,))
                share = cursor.fetchone()
                
                if not share:
                    return "Share link not found", 404
                
                # Check expiry
                if share.get('expires_at') and share['expires_at'] < datetime.now():
                    return "Share link expired", 410
                
                # Check max downloads
                if share.get('max_downloads') and share['download_count'] >= share['max_downloads']:
                    return "Download limit reached", 410
                
                # Check password
                if share.get('share_password') and not session.get(f'share_{token}'):
                    # Password protection - would need form handling
                    return "Password required"
                
                # Increment download count
                cursor.execute("UPDATE StudyMaterialShares SET download_count = download_count + 1 WHERE share_token = %s", (token,))
                cursor.execute("UPDATE StudyMaterials SET download_count = download_count + 1 WHERE id = %s", (share['material_id'],))
                
                material = share
            conn.commit()
        finally:
            conn.close()
    
    if not material or not material.get('file_path'):
        return "File not found", 404
    
    return send_file(material['file_path'], as_attachment=True)

@study_bp.route('/api/study/materials', methods=['POST'])
def add_material():
    if session.get('role') not in ['Admin', 'Coordinator']: return jsonify({'error': 'Unauthorized'}), 403
    
    topic_id = request.form.get('topic_id')
    title = request.form.get('title')
    mat_type = request.form.get('type')  # pdf, docx, pptx, video, notes
    content = request.form.get('content', '')
    video_url = request.form.get('video_url', '')
    is_public = 1 if request.form.get('is_public') == 'true' else 0
    release_date = request.form.get('release_date') or None
    
    batch_assignment = request.form.get('batch_assignment', '{}')
    tags = request.form.get('tags', '[]')
    
    file_path = None
    file_size = 0
    
    if mat_type in ['pdf', 'docx', 'pptx']:
        file = request.files.get('file')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            if not os.path.exists(UPLOAD_FOLDER):
                os.makedirs(UPLOAD_FOLDER)
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(file_path)
            file_size = os.path.getsize(file_path)

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO StudyMaterials 
                    (topic_id, title, type, file_path, video_url, content, file_size, tags, batch_assignment, is_public, release_date, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (topic_id, title, mat_type, file_path, video_url, content, file_size, tags, batch_assignment, is_public, release_date, session.get('user_id')))
            conn.commit()
            return jsonify({'message': 'Material added successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            conn.close()
    return jsonify({'error': 'Database error'}), 500

@study_bp.route('/api/study/materials/<int:material_id>', methods=['PUT', 'DELETE'])
def manage_material(material_id):
    if session.get('role') not in ['Admin', 'Coordinator']: return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db_connection()
    if not conn: return jsonify({'error': 'Database error'}), 500
    
    try:
        if request.method == 'DELETE':
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM StudyMaterialViews WHERE material_id=%s", (material_id,))
                cursor.execute("DELETE FROM StudyMaterials WHERE id=%s", (material_id,))
            conn.commit()
            return jsonify({'message': 'Deleted successfully'})
            
        elif request.method == 'PUT':
            title = request.form.get('title') or request.json.get('title')
            is_public_val = request.form.get('is_public') or request.json.get('is_public')
            is_public = 1 if is_public_val in ['true', True, 1, '1'] else 0
            batch_assignment = request.form.get('batch_assignment') or request.json.get('batch_assignment', '{}')
            tags = request.form.get('tags') or request.json.get('tags', '[]')
            
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE StudyMaterials 
                    SET title=%s, is_public=%s, batch_assignment=%s, tags=%s
                    WHERE id=%s
                """, (title, is_public, batch_assignment, tags, material_id))
            conn.commit()
            return jsonify({'message': 'Updated successfully'})
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@study_bp.route('/api/study/analytics', methods=['GET'])
def get_analytics():
    if session.get('role') not in ['Admin', 'Coordinator']: return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db_connection()
    if not conn: return jsonify({'error': 'Database error'}), 500
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT sm.id, sm.title, sm.type, COUNT(sv.id) as views
                FROM StudyMaterials sm
                LEFT JOIN StudyMaterialViews sv ON sm.id = sv.material_id
                GROUP BY sm.id, sm.title, sm.type
                ORDER BY views DESC
            """)
            analytics = cursor.fetchall()
            return jsonify({'analytics': analytics})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@study_bp.route('/api/study/subjects', methods=['POST'])
def add_subject():
    if session.get('role') not in ['Admin', 'Coordinator']: return jsonify({'error': 'Unauthorized'}), 403
    
    json_data = request.get_json(silent=True) or {}
    name = json_data.get('name')
    description = json_data.get('description', '')
    
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO StudySubjects (name, description, created_by) VALUES (%s, %s, %s)", 
                              (name, description, session.get('user_id')))
            conn.commit()
            return jsonify({'message': 'Subject added'})
        finally:
            conn.close()
    return jsonify({'error': 'Database error'}), 500

@study_bp.route('/api/study/chapters', methods=['POST'])
def add_chapter():
    if session.get('role') not in ['Admin', 'Coordinator']: return jsonify({'error': 'Unauthorized'}), 403
    
    json_data = request.get_json(silent=True) or {}
    subject_id = json_data.get('subject_id')
    name = json_data.get('name')
    description = json_data.get('description', '')
    
    if not name or not subject_id:
        return jsonify({'error': 'Name and subject_id are required'}), 400
    
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO StudyChapters (subject_id, name, description, created_by) VALUES (%s, %s, %s, %s)", 
                              (subject_id, name, description, session.get('user_id')))
            conn.commit()
            return jsonify({'message': 'Chapter added'})
        finally:
            conn.close()
    return jsonify({'error': 'Database error'}), 500

@study_bp.route('/api/study/topics', methods=['POST'])
def add_topic():
    if session.get('role') not in ['Admin', 'Coordinator']: 
        return jsonify({'error': 'Unauthorized'}), 403
    
    json_data = request.get_json(silent=True) or {}
    chapter_id = json_data.get('chapter_id')
    name = json_data.get('name')
    description = json_data.get('description', '')
    tags = json_data.get('tags')
    
    if not name or not chapter_id:
        return jsonify({'error': 'Name and chapter_id are required'}), 400
    
    # Ensure tags is proper JSON or NULL
    if tags is None:
        tags = None
    elif isinstance(tags, list):
        import json
        tags = json.dumps(tags)
    elif isinstance(tags, str):
        # Validate it's valid JSON
        try:
            import json
            json.loads(tags)
        except:
            tags = None
    else:
        tags = None
    
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                # Check if table exists first
                cursor.execute("SHOW TABLES LIKE 'StudyTopics'")
                if not cursor.fetchone():
                    return jsonify({'error': 'StudyTopics table does not exist. Please initialize the database schema.'}), 500
                
                # Try with created_by first, then without
                try:
                    cursor.execute("INSERT INTO StudyTopics (chapter_id, name, description, tags, created_by) VALUES (%s, %s, %s, %s, %s)", 
                                  (chapter_id, name, description, tags, session.get('user_id')))
                except Exception as e:
                    # Fallback if created_by doesn't exist
                    try:
                        cursor.execute("INSERT INTO StudyTopics (chapter_id, name, description, tags) VALUES (%s, %s, %s, %s)", 
                                      (chapter_id, name, description, tags))
                    except Exception as e2:
                        return jsonify({'error': f'Database error: {str(e2)}'}), 500
                        
                conn.commit()
                return jsonify({'message': 'Topic added successfully'})
        except Exception as e:
            print(f"Add topic error: {e}")
            return jsonify({'error': str(e)}), 500
        finally:
            conn.close()
    return jsonify({'error': 'Database connection error'}), 500

@study_bp.route('/api/study/subjects/<int:subject_id>', methods=['DELETE'])
def delete_subject(subject_id):
    if session.get('role') not in ['Admin', 'Coordinator']: return jsonify({'error': 'Unauthorized'}), 403
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM StudyTopics WHERE chapter_id IN (SELECT id FROM StudyChapters WHERE subject_id = %s)", (subject_id,))
                cursor.execute("DELETE FROM StudyChapters WHERE subject_id = %s", (subject_id,))
                cursor.execute("DELETE FROM StudySubjects WHERE id = %s", (subject_id,))
            conn.commit()
            return jsonify({'message': 'Subject deleted'})
        finally:
            conn.close()
    return jsonify({'error': 'Database error'}), 500

@study_bp.route('/api/study/chapters/<int:chapter_id>', methods=['DELETE'])
def delete_chapter(chapter_id):
    if session.get('role') not in ['Admin', 'Coordinator']: return jsonify({'error': 'Unauthorized'}), 403
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM StudyTopics WHERE chapter_id = %s", (chapter_id,))
                cursor.execute("DELETE FROM StudyChapters WHERE id = %s", (chapter_id,))
            conn.commit()
            return jsonify({'message': 'Chapter deleted'})
        finally:
            conn.close()
    return jsonify({'error': 'Database error'}), 500

@study_bp.route('/api/study/topics/<int:topic_id>', methods=['DELETE'])
def delete_topic(topic_id):
    if session.get('role') not in ['Admin', 'Coordinator']: return jsonify({'error': 'Unauthorized'}), 403
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM StudyTopics WHERE id = %s", (topic_id,))
            conn.commit()
            return jsonify({'message': 'Topic deleted'})
        finally:
            conn.close()
    return jsonify({'error': 'Database error'}), 500

# --- CATEGORIES MANAGEMENT ---
@study_bp.route('/api/study/categories', methods=['GET', 'POST'])
def manage_categories():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    if request.method == 'GET':
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM StudyCategories ORDER BY name")
                categories = cursor.fetchall()
            return jsonify(categories)
        finally:
            conn.close()
    
    # POST - requires auth
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    json_data = request.get_json(silent=True) or {}
    name = json_data.get('name')
    parent_id = json_data.get('parent_id')
    description = json_data.get('description', '')
    icon = json_data.get('icon', 'fa-folder')
    color = json_data.get('color', '#4f46e5')
    
    if not name:
        return jsonify({'error': 'Name required'}), 400
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO StudyCategories (name, parent_id, description, icon, color)
                VALUES (%s, %s, %s, %s, %s)
            """, (name, parent_id, description, icon, color))
        conn.commit()
        return jsonify({'message': 'Category created'})
    finally:
        conn.close()

@study_bp.route('/api/study/categories/<int:category_id>', methods=['PUT', 'DELETE'])
def manage_category(category_id):
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    try:
        with conn.cursor() as cursor:
            if request.method == 'DELETE':
                cursor.execute("DELETE FROM StudyCategories WHERE id = %s", (category_id,))
                return jsonify({'message': 'Category deleted'})
            
            # PUT - Update
            name = request.json.get('name')
            description = request.json.get('description')
            icon = request.json.get('icon')
            color = request.json.get('color')
            
            cursor.execute("""
                UPDATE StudyCategories 
                SET name = COALESCE(%s, name), 
                    description = COALESCE(%s, description),
                    icon = COALESCE(%s, icon),
                    color = COALESCE(%s, color)
                WHERE id = %s
            """, (name, description, icon, color, category_id))
        conn.commit()
        return jsonify({'message': 'Category updated'})
    finally:
        conn.close()

# --- MATERIAL VERSION CONTROL ---
@study_bp.route('/api/study/materials/<int:material_id>/versions', methods=['GET'])
def get_material_versions(material_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT v.*, u.full_name as created_by_name
                FROM StudyMaterialVersions v
                LEFT JOIN Users u ON v.created_by = u.user_id
                WHERE v.material_id = %s
                ORDER BY v.version_number DESC
            """, (material_id,))
            versions = cursor.fetchall()
        return jsonify(versions)
    finally:
        conn.close()

@study_bp.route('/api/study/materials/<int:material_id>/versions', methods=['POST'])
def create_new_version(material_id):
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    file = request.files.get('file')
    changes = request.form.get('changes', '')
    
    if not file:
        return jsonify({'error': 'File required'}), 400
    
    # Get current version number
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT MAX(version_number) as max_ver FROM StudyMaterialVersions WHERE material_id = %s", (material_id,))
            row = cursor.fetchone()
            new_version = (row['max_ver'] or 0) + 1
            
            # Save new version file
            original_filename = secure_filename(file.filename)
            filename = f"v{new_version}_{datetime.now().strftime('%Y%m%d')}_{original_filename}"
            
            if not os.path.exists(UPLOAD_FOLDER):
                os.makedirs(UPLOAD_FOLDER)
            
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(file_path)
            file_size = os.path.getsize(file_path)
            
            with open(file_path, 'rb') as f:
                checksum = calculate_checksum(f)
            
            cursor.execute("""
                INSERT INTO StudyMaterialVersions 
                (material_id, version_number, file_path, file_size, checksum, changes, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (material_id, new_version, file_path, file_size, checksum, changes, session.get('user_id')))
        conn.commit()
        return jsonify({'message': f'Version {new_version} created', 'version': new_version})
    finally:
        conn.close()

@study_bp.route('/api/study/materials/<int:material_id>/versions/<int:version_number>', methods=['GET'])
def download_version(material_id, version_number):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM StudyMaterialVersions WHERE material_id = %s AND version_number = %s",
                        (material_id, version_number))
            version = cursor.fetchone()
        return send_file(version['file_path'], as_attachment=True)
    finally:
        conn.close()

# --- MATERIAL COMMENTS ---
@study_bp.route('/api/study/materials/<int:material_id>/comments', methods=['GET', 'POST'])
def manage_comments(material_id):
    if not session.get('user_id'):
        return jsonify({'error': 'Login required'}), 401
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    try:
        with conn.cursor() as cursor:
            if request.method == 'GET':
                cursor.execute("""
                    SELECT c.*, u.full_name, u.avatar
                    FROM StudyMaterialComments c
                    JOIN Users u ON c.user_id = u.user_id
                    WHERE c.material_id = %s AND c.is_approved = 1
                    ORDER BY c.created_at DESC
                """, (material_id,))
                comments = cursor.fetchall()
                return jsonify(comments)
            
            # POST - Add comment
            content = request.json.get('content')
            rating = request.json.get('rating')
            parent_id = request.json.get('parent_id')
            
            if not content:
                return jsonify({'error': 'Content required'}), 400
            
            cursor.execute("""
                INSERT INTO StudyMaterialComments (material_id, user_id, content, rating, parent_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (material_id, session['user_id'], content, rating, parent_id))
        conn.commit()
        return jsonify({'message': 'Comment added'})
    finally:
        conn.close()

@study_bp.route('/api/study/materials/<int:material_id>/comments/<int:comment_id>', methods=['DELETE'])
def delete_comment(material_id, comment_id):
    if not session.get('user_id'):
        return jsonify({'error': 'Login required'}), 401
    
    # Check ownership or admin
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    try:
        with conn.cursor() as cursor:
            # Check if owner or admin
            cursor.execute("SELECT user_id FROM StudyMaterialComments WHERE id = %s", (comment_id,))
            comment = cursor.fetchone()
            
            if not comment:
                return jsonify({'error': 'Comment not found'}), 404
            
            if comment['user_id'] != session.get('user_id') and session.get('role') not in ['Admin', 'Coordinator']:
                return jsonify({'error': 'Unauthorized'}), 403
            
            cursor.execute("DELETE FROM StudyMaterialComments WHERE id = %s", (comment_id,))
        conn.commit()
        return jsonify({'message': 'Comment deleted'})
    finally:
        conn.close()

# --- BULK OPERATIONS ---
@study_bp.route('/api/study/materials/bulk', methods=['POST'])
def bulk_upload_materials():
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Handle multiple files
    files = request.files.getlist('files')
    topic_id = request.form.get('topic_id')
    is_public = 1 if request.form.get('is_public') == 'true' else 0
    
    if not topic_id or not files:
        return jsonify({'error': 'Topic and files required'}), 400
    
    session_token = secrets.token_hex(12)
    results = {'created': 0, 'failed': 0, 'errors': []}
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    try:
        with conn.cursor() as cursor:
            for file in files:
                valid, error = validate_file(file)
                if not valid:
                    results['failed'] += 1
                    results['errors'].append(f"{file.filename}: {error}")
                    continue
                
                original_filename = secure_filename(file.filename)
                filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}_{original_filename}"
                
                if not os.path.exists(UPLOAD_FOLDER):
                    os.makedirs(UPLOAD_FOLDER)
                
                file_path = os.path.join(UPLOAD_FOLDER, filename)
                file.save(file_path)
                file_size = os.path.getsize(file_path)
                
                mat_type = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else 'pdf'
                title = original_filename.rsplit('.', 1)[0]
                mime_type = get_mime_type(original_filename)
                
                with open(file_path, 'rb') as f:
                    checksum = calculate_checksum(f)
                
                cursor.execute("""
                    INSERT INTO StudyMaterials 
                    (topic_id, title, type, file_path, file_size, mime_type, original_filename,
                     checksum, is_public, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (topic_id, title, mat_type, file_path, file_size, mime_type, original_filename,
                     checksum, is_public, session.get('user_id')))
                
                results['created'] += 1
        conn.commit()
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@study_bp.route('/api/study/materials/bulk/delete', methods=['POST'])
def bulk_delete_materials():
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    material_ids = request.json.get('ids', [])
    
    if not material_ids:
        return jsonify({'error': 'No IDs provided'}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    try:
        with conn.cursor() as cursor:
            placeholders = ','.join(['%s'] * len(material_ids))
            cursor.execute(f"DELETE FROM StudyMaterials WHERE id IN ({placeholders})", tuple(material_ids))
            deleted = cursor.rowcount
        conn.commit()
        return jsonify({'message': f'{deleted} materials deleted'})
    finally:
        conn.close()

# --- REPORT MATERIAL ---
@study_bp.route('/api/study/materials/<int:material_id>/report', methods=['POST'])
def report_material(material_id):
    if not session.get('user_id'):
        return jsonify({'error': 'Login required'}), 401
    
    reason = request.json.get('reason')
    description = request.json.get('description', '')
    
    if not reason:
        return jsonify({'error': 'Reason required'}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO StudyMaterialReports (material_id, user_id, reason, description)
                VALUES (%s, %s, %s, %s)
            """, (material_id, session['user_id'], reason, description))
        conn.commit()
        return jsonify({'message': 'Report submitted'})
    finally:
        conn.close()

# --- EXPORT MATERIALS DATA ---
@study_bp.route('/api/study/export', methods=['GET'])
def export_materials():
    if session.get('role') not in ['Admin', 'Coordinator']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    format_type = request.args.get('format', 'csv')
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT sm.id, sm.title, sm.type, sm.file_size, sm.view_count, sm.download_count,
                       sm.rating, sm.is_public, sm.created_at,
                       st.name as topic_name, sc.name as chapter_name, ss.name as subject_name
                FROM StudyMaterials sm
                LEFT JOIN StudyTopics st ON sm.topic_id = st.id
                LEFT JOIN StudyChapters sc ON st.chapter_id = sc.id
                LEFT JOIN StudySubjects ss ON sc.subject_id = ss.id
                ORDER BY sm.created_at DESC
            """)
            materials = cursor.fetchall()
        
        if format_type == 'json':
            return jsonify(materials)
        
        # CSV export
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Title', 'Type', 'Size (bytes)', 'Views', 'Downloads', 
                         'Rating', 'Public', 'Created', 'Topic', 'Chapter', 'Subject'])
        
        for m in materials:
            writer.writerow([m['id'], m['title'], m['type'], m['file_size'], m['view_count'],
                           m['download_count'], m['rating'], m['is_public'], m['created_at'],
                           m['topic_name'], m['chapter_name'], m['subject_name']])
        
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=study_materials_{datetime.now().strftime('%Y%m%d')}.csv"}
        )
    finally:
        conn.close()

# --- USER BOOKMARKS LIST ---
@study_bp.route('/api/study/bookmarks', methods=['GET'])
def get_user_bookmarks():
    if not session.get('user_id'):
        return jsonify({'error': 'Login required'}), 401
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT b.*, sm.title, sm.type, sm.file_path, st.name as topic_name
                FROM StudyMaterialBookmarks b
                JOIN StudyMaterials sm ON b.material_id = sm.id
                LEFT JOIN StudyTopics st ON sm.topic_id = st.id
                WHERE b.user_id = %s
                ORDER BY b.created_at DESC
            """, (session['user_id'],))
            bookmarks = cursor.fetchall()
        return jsonify(bookmarks)
    finally:
        conn.close()
