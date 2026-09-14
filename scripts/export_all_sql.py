"""
Export complete database dump for both MySQL and Supabase (PostgreSQL).
Dumps all 27 tables and all rows and columns.
"""
import os
import re
import json
import pymysql
from decimal import Decimal
from datetime import datetime, date

TABLES_ORDER = [
    # Independent tables / lookups
    'exam_centers',
    'batches',
    'system_settings',
    'banners',
    'announcements',
    'judge_jobs',
    'studycategories',
    'studysubjects',
    
    # Tables depending on above
    'users',
    'official_assets',
    'quizzes',
    'studychapters',
    
    # Tables depending on quizzes / chapters / users
    'questions',
    'studytopics',
    'quiz_attempts',
    
    # Tables depending on questions / attempts / topics
    'questionsessionmapping',
    'quiz_responses',
    'studymaterials',
    
    # Tables depending on studymaterials
    'studymaterialbookmarks',
    'studymaterialcomments',
    'studymaterialratings',
    'studymaterialreports',
    'studymaterialshares',
    'studymaterialstats',
    'studymaterialversions',
    'studymaterialviews',
    
    # System audit logs
    'audit_logs'
]

def format_mysql_val(val):
    if val is None:
        return 'NULL'
    if isinstance(val, bool):
        return '1' if val else '0'
    if isinstance(val, (int, float, Decimal)):
        return str(val)
    if isinstance(val, (datetime, date)):
        return f"'{val.strftime('%Y-%m-%d %H:%M:%S')}'"
    if isinstance(val, (bytes, bytearray)):
        return f"X'{val.hex()}'"
    
    s = str(val)
    # MySQL escaping
    s = s.replace('\\', '\\\\').replace("'", "\\'").replace('\r', '\\r').replace('\n', '\\n').replace('\0', '\\0')
    return f"'{s}'"

def format_pg_val(val, is_bool=False):
    if val is None:
        return 'NULL'
    if is_bool or isinstance(val, bool):
        return 'TRUE' if val else 'FALSE'
    if isinstance(val, (int, float, Decimal)):
        return str(val)
    if isinstance(val, (datetime, date)):
        return f"'{val.strftime('%Y-%m-%d %H:%M:%S')}'"
    if isinstance(val, (bytes, bytearray)):
        return f"decode('{val.hex()}', 'hex')"
    
    s = str(val)
    # Standard PostgreSQL string literal escaping (single quote doubled)
    s = s.replace("'", "''")
    return f"'{s}'"

def dump_mysql(conn):
    lines = []
    lines.append("-- ============================================================================")
    lines.append("-- QUIZMASTER COMPLETE DATABASE DUMP (MySQL / MariaDB Compatible)")
    lines.append(f"-- Generated At: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append("-- Includes ALL 27 Tables, Columns, Constraints, and Complete Live Data Rows")
    lines.append("-- ============================================================================\n")
    lines.append("CREATE DATABASE IF NOT EXISTS `qcms_db` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;")
    lines.append("USE `qcms_db`;\n")
    lines.append("SET FOREIGN_KEY_CHECKS = 0;")
    lines.append("SET SQL_MODE = 'NO_AUTO_VALUE_ON_ZERO';")
    lines.append("SET NAMES utf8mb4;\n")
    
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # 1. Drop tables in reverse order
    lines.append("-- ----------------------------------------------------------------------------")
    lines.append("-- Drop Existing Tables")
    lines.append("-- ----------------------------------------------------------------------------")
    for t in reversed(TABLES_ORDER):
        lines.append(f"DROP TABLE IF EXISTS `{t}`;")
    lines.append("")

    # 2. Create tables and insert data in order
    for t in TABLES_ORDER:
        lines.append(f"-- ============================================================================")
        lines.append(f"-- Table structure & data for `{t}`")
        lines.append(f"-- ============================================================================")
        
        # Get CREATE TABLE
        raw_cur = conn.cursor()
        raw_cur.execute(f"SHOW CREATE TABLE `{t}`")
        create_sql = raw_cur.fetchone()[1]
        lines.append(f"{create_sql};\n")
        
        # Get rows
        cur.execute(f"SELECT * FROM `{t}`")
        rows = cur.fetchall()
        if rows:
            cols = list(rows[0].keys())
            cols_str = ", ".join([f"`{c}`" for c in cols])
            lines.append(f"-- Dumping data for table `{t}` ({len(rows)} rows)")
            
            # Batch inserts in chunks of 50
            chunk_size = 50
            for i in range(0, len(rows), chunk_size):
                chunk = rows[i:i+chunk_size]
                values_clauses = []
                for r in chunk:
                    val_strs = [format_mysql_val(r[c]) for c in cols]
                    values_clauses.append(f"  ({', '.join(val_strs)})")
                lines.append(f"INSERT INTO `{t}` ({cols_str}) VALUES\n" + ",\n".join(values_clauses) + ";\n")
        else:
            lines.append(f"-- (No rows to insert for `{t}`)\n")
            
    lines.append("SET FOREIGN_KEY_CHECKS = 1;")
    lines.append("-- ============================================================================")
    lines.append("-- END OF MYSQL COMPLETE DATABASE DUMP")
    lines.append("-- ============================================================================")
    
    return "\n".join(lines)

def build_supabase_schema():
    """Returns PostgreSQL DDL for Supabase matching all 27 tables."""
    return """-- ============================================================================
-- QUIZMASTER COMPLETE DATABASE SCHEMA & DATA FOR SUPABASE (PostgreSQL)
-- ============================================================================
-- Instructions:
-- 1. Open your Supabase Project Dashboard
-- 2. Click on 'SQL Editor' in the left navigation sidebar
-- 3. Click '+ New query'
-- 4. Paste this entire file into the SQL Editor and click 'Run'
-- All 27 tables, constraints, sequences, and data rows will be initialized.
-- ============================================================================

-- Disable notices during execution
SET client_min_messages = warning;

-- Drop existing tables in reverse dependency order
DROP TABLE IF EXISTS studymaterialviews CASCADE;
DROP TABLE IF EXISTS studymaterialversions CASCADE;
DROP TABLE IF EXISTS studymaterialstats CASCADE;
DROP TABLE IF EXISTS studymaterialshares CASCADE;
DROP TABLE IF EXISTS studymaterialreports CASCADE;
DROP TABLE IF EXISTS studymaterialratings CASCADE;
DROP TABLE IF EXISTS studymaterialcomments CASCADE;
DROP TABLE IF EXISTS studymaterialbookmarks CASCADE;
DROP TABLE IF EXISTS studymaterials CASCADE;
DROP TABLE IF EXISTS quiz_responses CASCADE;
DROP TABLE IF EXISTS questionsessionmapping CASCADE;
DROP TABLE IF EXISTS quiz_attempts CASCADE;
DROP TABLE IF EXISTS studytopics CASCADE;
DROP TABLE IF EXISTS questions CASCADE;
DROP TABLE IF EXISTS studychapters CASCADE;
DROP TABLE IF EXISTS quizzes CASCADE;
DROP TABLE IF EXISTS official_assets CASCADE;
DROP TABLE IF EXISTS audit_logs CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS studysubjects CASCADE;
DROP TABLE IF EXISTS studycategories CASCADE;
DROP TABLE IF EXISTS judge_jobs CASCADE;
DROP TABLE IF EXISTS announcements CASCADE;
DROP TABLE IF EXISTS banners CASCADE;
DROP TABLE IF EXISTS system_settings CASCADE;
DROP TABLE IF EXISTS batches CASCADE;
DROP TABLE IF EXISTS exam_centers CASCADE;

-- ----------------------------------------------------------------------------
-- 1. exam_centers
-- ----------------------------------------------------------------------------
CREATE TABLE exam_centers (
  center_id SERIAL PRIMARY KEY,
  center_name VARCHAR(255) NOT NULL,
  city VARCHAR(100) DEFAULT NULL,
  address TEXT DEFAULT NULL,
  total_rows INTEGER DEFAULT 0,
  total_cols INTEGER DEFAULT 0,
  capacity INTEGER DEFAULT 0,
  allocated_count INTEGER DEFAULT 0
);

-- ----------------------------------------------------------------------------
-- 2. batches
-- ----------------------------------------------------------------------------
CREATE TABLE batches (
  batch_id SERIAL PRIMARY KEY,
  batch_name VARCHAR(100) NOT NULL UNIQUE
);

-- ----------------------------------------------------------------------------
-- 3. system_settings
-- ----------------------------------------------------------------------------
CREATE TABLE system_settings (
  setting_key VARCHAR(100) PRIMARY KEY,
  setting_value TEXT DEFAULT NULL
);

-- ----------------------------------------------------------------------------
-- 4. banners
-- ----------------------------------------------------------------------------
CREATE TABLE banners (
  id SERIAL PRIMARY KEY,
  image_data TEXT DEFAULT NULL,
  caption VARCHAR(255) DEFAULT NULL
);

-- ----------------------------------------------------------------------------
-- 5. announcements
-- ----------------------------------------------------------------------------
CREATE TABLE announcements (
  id INTEGER PRIMARY KEY,
  message TEXT DEFAULT NULL,
  is_active BOOLEAN DEFAULT FALSE
);

-- ----------------------------------------------------------------------------
-- 6. judge_jobs
-- ----------------------------------------------------------------------------
CREATE TABLE judge_jobs (
  job_id VARCHAR(64) PRIMARY KEY,
  status VARCHAR(32) DEFAULT NULL,
  verdict VARCHAR(32) DEFAULT NULL,
  output TEXT DEFAULT NULL,
  execution_time REAL DEFAULT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 7. studycategories
-- ----------------------------------------------------------------------------
CREATE TABLE studycategories (
  id SERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  parent_id INTEGER DEFAULT NULL,
  description TEXT DEFAULT NULL,
  icon VARCHAR(50) DEFAULT NULL,
  color VARCHAR(20) DEFAULT NULL
);
CREATE INDEX idx_study_categories_parent_id ON studycategories(parent_id);

-- ----------------------------------------------------------------------------
-- 8. studysubjects
-- ----------------------------------------------------------------------------
CREATE TABLE studysubjects (
  id SERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  description TEXT DEFAULT NULL,
  created_by INTEGER DEFAULT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_study_subjects_created_by ON studysubjects(created_by);

-- ----------------------------------------------------------------------------
-- 9. users
-- ----------------------------------------------------------------------------
CREATE TABLE users (
  user_id SERIAL PRIMARY KEY,
  full_name VARCHAR(255) NOT NULL,
  role VARCHAR(50) DEFAULT 'Student' CHECK (role IN ('Admin', 'Coordinator', 'Student')),
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  mobile VARCHAR(20) DEFAULT NULL,
  phone_number VARCHAR(20) DEFAULT NULL,
  enrolled_session VARCHAR(100) DEFAULT NULL,
  selected_session VARCHAR(100) DEFAULT NULL,
  occupation VARCHAR(50) DEFAULT NULL,
  college VARCHAR(255) DEFAULT NULL,
  department VARCHAR(255) DEFAULT NULL,
  section VARCHAR(50) DEFAULT NULL,
  study_year VARCHAR(20) DEFAULT NULL,
  roll_number VARCHAR(50) DEFAULT NULL,
  designation VARCHAR(100) DEFAULT NULL,
  goal_type VARCHAR(50) DEFAULT NULL,
  team_name VARCHAR(100) DEFAULT NULL,
  team_members TEXT DEFAULT NULL,
  is_blocked BOOLEAN DEFAULT FALSE,
  attendance_present INTEGER DEFAULT 0,
  attendance_total INTEGER DEFAULT 0,
  allotted_center_id INTEGER DEFAULT NULL REFERENCES exam_centers(center_id) ON DELETE SET NULL,
  center_id INTEGER DEFAULT NULL REFERENCES exam_centers(center_id) ON DELETE SET NULL,
  seat_row INTEGER DEFAULT NULL,
  seat_col INTEGER DEFAULT NULL,
  avatar TEXT DEFAULT NULL,
  last_year_update DATE DEFAULT NULL,
  active_session_token VARCHAR(64) DEFAULT NULL,
  last_active_time TIMESTAMP WITH TIME ZONE DEFAULT NULL,
  must_change_password BOOLEAN DEFAULT FALSE,
  temporary_password_created_at TIMESTAMP WITH TIME ZONE DEFAULT NULL,
  password_changed_at TIMESTAMP WITH TIME ZONE DEFAULT NULL,
  created_by INTEGER DEFAULT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_users_role ON users(role);
CREATE INDEX idx_users_batch ON users(enrolled_session);
CREATE INDEX idx_users_department ON users(department);
CREATE INDEX idx_users_center_id ON users(center_id);
CREATE INDEX idx_users_allotted_center_id ON users(allotted_center_id);

-- ----------------------------------------------------------------------------
-- 10. official_assets
-- ----------------------------------------------------------------------------
CREATE TABLE official_assets (
  id SERIAL PRIMARY KEY,
  asset_type VARCHAR(50) NOT NULL CHECK (asset_type IN ('program_director_signature', 'official_seal')),
  file_path VARCHAR(255) NOT NULL,
  original_file_name VARCHAR(255) NOT NULL,
  mime_type VARCHAR(100) NOT NULL,
  file_size INTEGER NOT NULL,
  is_active BOOLEAN DEFAULT FALSE,
  uploaded_by INTEGER DEFAULT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_asset_type_active ON official_assets(asset_type, is_active);

-- ----------------------------------------------------------------------------
-- 11. quizzes
-- ----------------------------------------------------------------------------
CREATE TABLE quizzes (
  quiz_id SERIAL PRIMARY KEY,
  title VARCHAR(255) NOT NULL,
  marks INTEGER DEFAULT NULL,
  category VARCHAR(100) DEFAULT 'General',
  duration_minutes INTEGER DEFAULT 60,
  total_marks INTEGER DEFAULT 0,
  start_time TIMESTAMP WITH TIME ZONE DEFAULT NULL,
  instructions TEXT DEFAULT NULL,
  reg_status BOOLEAN DEFAULT TRUE,
  batch VARCHAR(100) DEFAULT NULL,
  department VARCHAR(255) DEFAULT NULL,
  section VARCHAR(50) DEFAULT NULL,
  year VARCHAR(20) DEFAULT NULL
);
CREATE INDEX idx_quizzes_batch ON quizzes(batch);
CREATE INDEX idx_quizzes_reg_status ON quizzes(reg_status);
CREATE INDEX idx_quizzes_start_time ON quizzes(start_time);

-- ----------------------------------------------------------------------------
-- 12. studychapters
-- ----------------------------------------------------------------------------
CREATE TABLE studychapters (
  id SERIAL PRIMARY KEY,
  subject_id INTEGER NOT NULL REFERENCES studysubjects(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL,
  description TEXT DEFAULT NULL,
  created_by INTEGER DEFAULT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_study_chapters_subject_id ON studychapters(subject_id);
CREATE INDEX idx_study_chapters_created_by ON studychapters(created_by);

-- ----------------------------------------------------------------------------
-- 13. questions
-- ----------------------------------------------------------------------------
CREATE TABLE questions (
  question_id SERIAL PRIMARY KEY,
  quiz_id INTEGER NOT NULL REFERENCES quizzes(quiz_id) ON DELETE CASCADE,
  question_text TEXT NOT NULL,
  correct_option VARCHAR(10) DEFAULT NULL,
  marks INTEGER DEFAULT 1,
  option_a TEXT DEFAULT NULL,
  option_b TEXT DEFAULT NULL,
  option_c TEXT DEFAULT NULL,
  option_d TEXT DEFAULT NULL,
  question_type VARCHAR(50) DEFAULT 'mcq_single',
  test_input TEXT DEFAULT NULL,
  test_output TEXT DEFAULT NULL,
  module VARCHAR(100) DEFAULT 'General',
  batch VARCHAR(100) DEFAULT NULL,
  session_title VARCHAR(255) DEFAULT NULL,
  category VARCHAR(100) DEFAULT 'General',
  source VARCHAR(50) DEFAULT 'AI Generated',
  tags VARCHAR(255) DEFAULT '',
  explanation TEXT DEFAULT NULL,
  blooms_level VARCHAR(50) DEFAULT 'Apply',
  difficulty VARCHAR(50) DEFAULT 'Medium',
  remarks TEXT DEFAULT NULL,
  metadata_json TEXT DEFAULT NULL,
  scoring_type VARCHAR(50) DEFAULT 'all_or_nothing',
  negative_marks REAL DEFAULT 0,
  status VARCHAR(20) DEFAULT 'Published',
  subject VARCHAR(100) DEFAULT 'General',
  topic VARCHAR(100) DEFAULT '',
  chapter VARCHAR(100) DEFAULT '',
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_questions_quiz_id ON questions(quiz_id);
CREATE INDEX idx_questions_module ON questions(module);

-- ----------------------------------------------------------------------------
-- 14. studytopics
-- ----------------------------------------------------------------------------
CREATE TABLE studytopics (
  id SERIAL PRIMARY KEY,
  chapter_id INTEGER NOT NULL REFERENCES studychapters(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL,
  description TEXT DEFAULT NULL,
  tags TEXT DEFAULT NULL,
  created_by INTEGER DEFAULT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_study_topics_chapter_id ON studytopics(chapter_id);
CREATE INDEX idx_study_topics_created_by ON studytopics(created_by);

-- ----------------------------------------------------------------------------
-- 15. quiz_attempts
-- ----------------------------------------------------------------------------
CREATE TABLE quiz_attempts (
  attempt_id SERIAL PRIMARY KEY,
  user_id INTEGER DEFAULT NULL REFERENCES users(user_id) ON DELETE SET NULL,
  quiz_id INTEGER DEFAULT NULL REFERENCES quizzes(quiz_id) ON DELETE SET NULL,
  total_score NUMERIC(10,2) DEFAULT 0.00,
  status VARCHAR(50) DEFAULT 'In-Progress' CHECK (status IN ('In-Progress', 'Completed', 'Terminated')),
  cheat_detected BOOLEAN DEFAULT FALSE,
  certificate_approved BOOLEAN DEFAULT FALSE,
  start_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  end_time TIMESTAMP WITH TIME ZONE DEFAULT NULL,
  submitted_at TIMESTAMP WITH TIME ZONE DEFAULT NULL,
  is_winner BOOLEAN DEFAULT FALSE,
  quiz_title VARCHAR(255) DEFAULT NULL,
  total_marks NUMERIC(10,2) DEFAULT 100.00,
  batch VARCHAR(100) DEFAULT NULL,
  total_questions INTEGER DEFAULT 0
);
CREATE INDEX idx_quiz_attempts_user_id ON quiz_attempts(user_id);
CREATE INDEX idx_quiz_attempts_quiz_id ON quiz_attempts(quiz_id);

-- ----------------------------------------------------------------------------
-- 16. questionsessionmapping
-- ----------------------------------------------------------------------------
CREATE TABLE questionsessionmapping (
  id SERIAL PRIMARY KEY,
  question_id INTEGER DEFAULT NULL,
  quiz_id INTEGER DEFAULT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT unique_q_session UNIQUE (question_id, quiz_id)
);

-- ----------------------------------------------------------------------------
-- 17. quiz_responses
-- ----------------------------------------------------------------------------
CREATE TABLE quiz_responses (
  response_id SERIAL PRIMARY KEY,
  attempt_id INTEGER NOT NULL REFERENCES quiz_attempts(attempt_id) ON DELETE CASCADE,
  question_id INTEGER NOT NULL REFERENCES questions(question_id) ON DELETE CASCADE,
  selected_option TEXT DEFAULT NULL,
  is_attempted BOOLEAN DEFAULT FALSE,
  is_flagged BOOLEAN DEFAULT FALSE,
  CONSTRAINT unique_response UNIQUE (attempt_id, question_id)
);
CREATE INDEX idx_quiz_responses_question_id ON quiz_responses(question_id);

-- ----------------------------------------------------------------------------
-- 18. studymaterials
-- ----------------------------------------------------------------------------
CREATE TABLE studymaterials (
  id SERIAL PRIMARY KEY,
  topic_id INTEGER NOT NULL REFERENCES studytopics(id) ON DELETE CASCADE,
  title VARCHAR(255) NOT NULL,
  type VARCHAR(50) NOT NULL,
  file_path VARCHAR(500) DEFAULT NULL,
  video_url VARCHAR(500) DEFAULT NULL,
  content TEXT DEFAULT NULL,
  file_size BIGINT DEFAULT 0,
  tags TEXT DEFAULT NULL,
  batch_assignment TEXT DEFAULT NULL,
  is_public BOOLEAN DEFAULT FALSE,
  is_featured BOOLEAN DEFAULT FALSE,
  difficulty VARCHAR(20) DEFAULT 'intermediate',
  duration_minutes INTEGER DEFAULT 0,
  rating NUMERIC(3,2) DEFAULT 0.00,
  rating_count INTEGER DEFAULT 0,
  view_count INTEGER DEFAULT 0,
  download_count INTEGER DEFAULT 0,
  release_date DATE DEFAULT NULL,
  created_by INTEGER DEFAULT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  mime_type VARCHAR(100) DEFAULT NULL,
  original_filename VARCHAR(255) DEFAULT NULL,
  checksum VARCHAR(64) DEFAULT NULL,
  description TEXT DEFAULT NULL,
  ai_tags TEXT DEFAULT NULL,
  objectives TEXT DEFAULT NULL
);
CREATE INDEX idx_study_materials_topic_id ON studymaterials(topic_id);
CREATE INDEX idx_study_materials_created_by ON studymaterials(created_by);

-- ----------------------------------------------------------------------------
-- 19. studymaterialbookmarks
-- ----------------------------------------------------------------------------
CREATE TABLE studymaterialbookmarks (
  id SERIAL PRIMARY KEY,
  material_id INTEGER NOT NULL REFERENCES studymaterials(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  note TEXT DEFAULT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT unique_bookmark UNIQUE (material_id, user_id)
);
CREATE INDEX idx_study_material_bookmarks_material_id ON studymaterialbookmarks(material_id);
CREATE INDEX idx_study_material_bookmarks_user_id ON studymaterialbookmarks(user_id);

-- ----------------------------------------------------------------------------
-- 20. studymaterialcomments
-- ----------------------------------------------------------------------------
CREATE TABLE studymaterialcomments (
  id SERIAL PRIMARY KEY,
  material_id INTEGER NOT NULL REFERENCES studymaterials(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  content TEXT DEFAULT NULL,
  rating INTEGER DEFAULT NULL,
  parent_id INTEGER DEFAULT NULL,
  is_approved BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_study_material_comments_material_id ON studymaterialcomments(material_id);
CREATE INDEX idx_study_material_comments_user_id ON studymaterialcomments(user_id);
CREATE INDEX idx_study_material_comments_parent_id ON studymaterialcomments(parent_id);

-- ----------------------------------------------------------------------------
-- 21. studymaterialratings
-- ----------------------------------------------------------------------------
CREATE TABLE studymaterialratings (
  id SERIAL PRIMARY KEY,
  material_id INTEGER NOT NULL REFERENCES studymaterials(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  rating INTEGER NOT NULL,
  comment TEXT DEFAULT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT unique_user_material_rating UNIQUE (material_id, user_id)
);
CREATE INDEX idx_study_material_ratings_material_id ON studymaterialratings(material_id);
CREATE INDEX idx_study_material_ratings_user_id ON studymaterialratings(user_id);

-- ----------------------------------------------------------------------------
-- 22. studymaterialreports
-- ----------------------------------------------------------------------------
CREATE TABLE studymaterialreports (
  id SERIAL PRIMARY KEY,
  material_id INTEGER NOT NULL REFERENCES studymaterials(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  reason VARCHAR(255) DEFAULT NULL,
  description TEXT DEFAULT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_study_material_reports_material_id ON studymaterialreports(material_id);
CREATE INDEX idx_study_material_reports_user_id ON studymaterialreports(user_id);

-- ----------------------------------------------------------------------------
-- 23. studymaterialshares
-- ----------------------------------------------------------------------------
CREATE TABLE studymaterialshares (
  id SERIAL PRIMARY KEY,
  material_id INTEGER NOT NULL REFERENCES studymaterials(id) ON DELETE CASCADE,
  share_token VARCHAR(100) NOT NULL UNIQUE,
  access_type VARCHAR(20) DEFAULT 'private',
  expires_at TIMESTAMP WITH TIME ZONE DEFAULT NULL,
  max_downloads INTEGER DEFAULT NULL,
  share_password VARCHAR(255) DEFAULT NULL,
  download_count INTEGER DEFAULT 0,
  created_by INTEGER DEFAULT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_study_material_shares_material_id ON studymaterialshares(material_id);

-- ----------------------------------------------------------------------------
-- 24. studymaterialstats
-- ----------------------------------------------------------------------------
CREATE TABLE studymaterialstats (
  id SERIAL PRIMARY KEY,
  material_id INTEGER NOT NULL REFERENCES studymaterials(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  downloads INTEGER DEFAULT 0,
  views INTEGER DEFAULT 0,
  unique_viewers INTEGER DEFAULT 0
);
CREATE INDEX idx_study_material_stats_material_id ON studymaterialstats(material_id);
CREATE INDEX idx_study_material_stats_date ON studymaterialstats(date);

-- ----------------------------------------------------------------------------
-- 25. studymaterialversions
-- ----------------------------------------------------------------------------
CREATE TABLE studymaterialversions (
  id SERIAL PRIMARY KEY,
  material_id INTEGER NOT NULL REFERENCES studymaterials(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  file_path VARCHAR(500) DEFAULT NULL,
  file_size BIGINT DEFAULT 0,
  checksum VARCHAR(64) DEFAULT NULL,
  changes TEXT DEFAULT NULL,
  created_by INTEGER DEFAULT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_study_material_versions_material_id ON studymaterialversions(material_id);

-- ----------------------------------------------------------------------------
-- 26. studymaterialviews
-- ----------------------------------------------------------------------------
CREATE TABLE studymaterialviews (
  id SERIAL PRIMARY KEY,
  material_id INTEGER NOT NULL REFERENCES studymaterials(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  viewed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_study_material_views_material_id ON studymaterialviews(material_id);
CREATE INDEX idx_study_material_views_user_id ON studymaterialviews(user_id);

-- ----------------------------------------------------------------------------
-- 27. audit_logs
-- ----------------------------------------------------------------------------
CREATE TABLE audit_logs (
  audit_id SERIAL PRIMARY KEY,
  user_id INTEGER DEFAULT NULL,
  action VARCHAR(128) NOT NULL,
  ip_address VARCHAR(64) DEFAULT NULL,
  user_agent VARCHAR(255) DEFAULT NULL,
  details TEXT DEFAULT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);

"""

# Boolean column registry for Postgres formatting
PG_BOOLEAN_COLUMNS = {
    'announcements': {'is_active'},
    'users': {'is_blocked', 'must_change_password'},
    'official_assets': {'is_active'},
    'quizzes': {'reg_status'},
    'quiz_attempts': {'cheat_detected', 'certificate_approved', 'is_winner'},
    'quiz_responses': {'is_attempted', 'is_flagged'},
    'studymaterials': {'is_public', 'is_featured'},
    'studymaterialcomments': {'is_approved'},
}

def dump_supabase(conn):
    lines = [build_supabase_schema()]
    lines.append("-- ============================================================================")
    lines.append("-- DATA INSERTION (Converted for PostgreSQL / Supabase)")
    lines.append("-- ============================================================================\n")
    
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    for t in TABLES_ORDER:
        cur.execute(f"SELECT * FROM `{t}`")
        rows = cur.fetchall()
        if rows:
            cols = list(rows[0].keys())
            # For postgres, use clean identifiers
            cols_str = ", ".join([f'"{c}"' for c in cols])
            lines.append(f"-- Data for {t} ({len(rows)} rows)")
            
            bool_cols = PG_BOOLEAN_COLUMNS.get(t, set())
            
            chunk_size = 50
            for i in range(0, len(rows), chunk_size):
                chunk = rows[i:i+chunk_size]
                values_clauses = []
                for r in chunk:
                    val_strs = [format_pg_val(r[c], is_bool=(c in bool_cols)) for c in cols]
                    values_clauses.append(f"  ({', '.join(val_strs)})")
                lines.append(f'INSERT INTO "{t}" ({cols_str}) VALUES\n' + ",\n".join(values_clauses) + ";\n")
        else:
            lines.append(f"-- No rows for {t}\n")

    # Sequence reset statements so Supabase serial keys continue properly
    lines.append("-- ============================================================================")
    lines.append("-- RESET SEQUENCES TO MATCH INSERTED MAX IDS")
    lines.append("-- ============================================================================")
    seq_tables = [
        ('exam_centers', 'center_id'),
        ('batches', 'batch_id'),
        ('banners', 'id'),
        ('users', 'user_id'),
        ('official_assets', 'id'),
        ('quizzes', 'quiz_id'),
        ('studycategories', 'id'),
        ('studysubjects', 'id'),
        ('studychapters', 'id'),
        ('questions', 'question_id'),
        ('studytopics', 'id'),
        ('quiz_attempts', 'attempt_id'),
        ('questionsessionmapping', 'id'),
        ('quiz_responses', 'response_id'),
        ('studymaterials', 'id'),
        ('studymaterialbookmarks', 'id'),
        ('studymaterialcomments', 'id'),
        ('studymaterialratings', 'id'),
        ('studymaterialreports', 'id'),
        ('studymaterialshares', 'id'),
        ('studymaterialstats', 'id'),
        ('studymaterialversions', 'id'),
        ('studymaterialviews', 'id'),
        ('audit_logs', 'audit_id')
    ]
    
    for table_name, id_col in seq_tables:
        lines.append(f"SELECT setval(pg_get_serial_sequence('{table_name}', '{id_col}'), COALESCE((SELECT MAX(\"{id_col}\") FROM \"{table_name}\"), 1));")
        
    lines.append("\n-- ============================================================================")
    lines.append("-- SUPABASE DATABASE SETUP COMPLETE")
    lines.append("-- ============================================================================")
    
    return "\n".join(lines)

def main():
    conn = pymysql.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', 'qcms_db')
    )
    
    print("Generating MySQL database complete dump...")
    mysql_dump = dump_mysql(conn)
    with open('qcms_db_complete.sql', 'w', encoding='utf-8') as f:
        f.write(mysql_dump)
    # Also update the canonical qcms_db.sql
    with open('qcms_db.sql', 'w', encoding='utf-8') as f:
        f.write(mysql_dump)
    print("Saved qcms_db_complete.sql and updated qcms_db.sql.")
    
    print("Generating Supabase (PostgreSQL) database complete dump...")
    supabase_dump = dump_supabase(conn)
    with open('supabase_complete.sql', 'w', encoding='utf-8') as f:
        f.write(supabase_dump)
    print("Saved supabase_complete.sql.")
    
    conn.close()
    print("\nSUCCESS! All tables and data rows dumped successfully.")

if __name__ == '__main__':
    main()
