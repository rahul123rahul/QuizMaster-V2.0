-- =============================================================================
-- QUIZMASTER ENTERPRISE PRODUCTION DATABASE SCHEMA
-- Compatible with MySQL 8.0+ and MariaDB 10.5+ (utf8mb4 charset)
-- =============================================================================

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS Quiz_Responses;
DROP TABLE IF EXISTS Quiz_Attempts;
DROP TABLE IF EXISTS Questions;
DROP TABLE IF EXISTS QuestionSessionMapping;
DROP TABLE IF EXISTS Quizzes;
DROP TABLE IF EXISTS official_assets;
DROP TABLE IF EXISTS audit_logs;
DROP TABLE IF EXISTS judge_jobs;
DROP TABLE IF EXISTS Users;
DROP TABLE IF EXISTS Batches;
DROP TABLE IF EXISTS Banners;
DROP TABLE IF EXISTS Exam_Centers;
DROP TABLE IF EXISTS Announcements;
DROP TABLE IF EXISTS system_settings;

SET FOREIGN_KEY_CHECKS = 1;

-- -----------------------------------------------------------------------------
-- 1. Core Structure & Sessions
-- -----------------------------------------------------------------------------
CREATE TABLE Batches (
    batch_id INT AUTO_INCREMENT PRIMARY KEY,
    batch_name VARCHAR(100) NOT NULL UNIQUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE Exam_Centers (
    center_id INT AUTO_INCREMENT PRIMARY KEY,
    center_name VARCHAR(255) NOT NULL,
    city VARCHAR(100),
    address TEXT,
    total_rows INT DEFAULT 0,
    total_cols INT DEFAULT 0,
    capacity INT DEFAULT 0,
    allocated_count INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 2. Users Table with Single-Device Concurrency & Password Policy Controls
-- -----------------------------------------------------------------------------
CREATE TABLE Users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    mobile VARCHAR(20),
    phone_number VARCHAR(20),
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('Student', 'Admin', 'Coordinator') DEFAULT 'Student',

    -- Student & Academic Details
    enrolled_session VARCHAR(100),
    selected_session VARCHAR(100),
    occupation VARCHAR(50),
    college VARCHAR(255),
    department VARCHAR(100),
    section VARCHAR(50),
    study_year VARCHAR(20),
    roll_number VARCHAR(50),
    designation VARCHAR(100),

    -- Team Participation
    goal_type VARCHAR(50),
    team_name VARCHAR(100),
    team_members TEXT,

    -- Security, Attendance, Concurrency & Policy
    is_blocked TINYINT(1) DEFAULT 0,
    attendance_present INT DEFAULT 0,
    attendance_total INT DEFAULT 0,
    avatar TEXT,
    last_year_update DATE,

    -- Single Device Session Token & Inactivity Tracking
    active_session_token VARCHAR(255) NULL,
    last_active_time BIGINT NULL,

    -- First Login Password Policy
    must_change_password TINYINT(1) DEFAULT 0,
    temporary_password_created_at DATETIME NULL,
    password_changed_at DATETIME NULL,
    created_by INT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- Center Allocation
    allotted_center_id INT NULL,
    center_id INT NULL,
    seat_row INT NULL,
    seat_col INT NULL,

    INDEX idx_user_email (email),
    INDEX idx_user_role (role),
    INDEX idx_user_roll (roll_number),
    INDEX idx_user_session (enrolled_session),
    FOREIGN KEY (allotted_center_id) REFERENCES Exam_Centers(center_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 3. Quizzes & Assessments
-- -----------------------------------------------------------------------------
CREATE TABLE Quizzes (
    quiz_id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    duration_minutes INT DEFAULT 60,
    total_marks INT DEFAULT 0,
    start_time DATETIME NULL,
    instructions TEXT,
    reg_status TINYINT(1) DEFAULT 1,

    -- Filters & Batches
    batch VARCHAR(100),
    department VARCHAR(255),
    section VARCHAR(50),
    year VARCHAR(255),

    INDEX idx_quiz_batch (batch)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 4. Question Bank (MCQ, Coding & Advanced Questions)
-- -----------------------------------------------------------------------------
CREATE TABLE Questions (
    question_id INT AUTO_INCREMENT PRIMARY KEY,
    quiz_id INT NOT NULL,
    question_type VARCHAR(20) DEFAULT 'MCQ',
    question_text TEXT NOT NULL,

    -- MCQ Options
    option_a TEXT,
    option_b TEXT,
    option_c TEXT,
    option_d TEXT,
    correct_option VARCHAR(255),

    -- Coding & Testing
    test_input TEXT,
    test_output TEXT,

    marks INT DEFAULT 1,
    module VARCHAR(100) DEFAULT 'General',
    subject VARCHAR(100) DEFAULT 'General',
    difficulty VARCHAR(50) DEFAULT 'Medium',
    status VARCHAR(50) DEFAULT 'Published',
    explanation TEXT,
    negative_marks FLOAT DEFAULT 0.0,
    metadata_json TEXT,

    INDEX idx_question_quiz (quiz_id),
    INDEX idx_question_module (module),
    FOREIGN KEY (quiz_id) REFERENCES Quizzes(quiz_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 5. Quiz Attempts & Responses
-- -----------------------------------------------------------------------------
CREATE TABLE Quiz_Attempts (
    attempt_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NULL,
    quiz_id INT NULL,
    total_score FLOAT DEFAULT 0.0,
    status ENUM('In-Progress', 'Completed', 'Terminated') DEFAULT 'In-Progress',
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_time DATETIME NULL,
    submitted_at DATETIME NULL,
    cheat_detected TINYINT(1) DEFAULT 0,
    certificate_approved TINYINT(1) DEFAULT 0,
    is_winner TINYINT(1) DEFAULT 0,
    quiz_title VARCHAR(255),
    total_marks FLOAT DEFAULT 100.0,
    batch VARCHAR(100),
    total_questions INT DEFAULT 0,

    INDEX idx_attempt_user (user_id),
    INDEX idx_attempt_quiz (quiz_id),
    INDEX idx_attempt_status (status),
    FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE SET NULL,
    FOREIGN KEY (quiz_id) REFERENCES Quizzes(quiz_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE Quiz_Responses (
    response_id INT AUTO_INCREMENT PRIMARY KEY,
    attempt_id INT NOT NULL,
    question_id INT NOT NULL,
    selected_option TEXT,
    is_attempted TINYINT(1) DEFAULT 0,

    UNIQUE KEY unique_response (attempt_id, question_id),
    INDEX idx_resp_attempt (attempt_id),
    INDEX idx_resp_question (question_id),
    FOREIGN KEY (attempt_id) REFERENCES Quiz_Attempts(attempt_id) ON DELETE CASCADE,
    FOREIGN KEY (question_id) REFERENCES Questions(question_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 6. Official Assets (Director Signature & Institutional Seal)
-- -----------------------------------------------------------------------------
CREATE TABLE official_assets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    asset_type ENUM('program_director_signature', 'official_seal') NOT NULL,
    file_path VARCHAR(255) NOT NULL,
    original_file_name VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    file_size INT NOT NULL,
    is_active TINYINT(1) DEFAULT 0,
    uploaded_by INT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_asset_type_active (asset_type, is_active),
    FOREIGN KEY (uploaded_by) REFERENCES Users(user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 7. Audit Logging & System Settings
-- -----------------------------------------------------------------------------
CREATE TABLE audit_logs (
    audit_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NULL,
    action VARCHAR(128) NOT NULL,
    ip_address VARCHAR(64) NULL,
    user_agent VARCHAR(255) NULL,
    details TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_audit_user (user_id),
    INDEX idx_audit_action (action)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE system_settings (
    setting_key VARCHAR(100) PRIMARY KEY,
    setting_value LONGTEXT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE judge_jobs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    token VARCHAR(255),
    source_code LONGTEXT,
    language_id INT,
    status VARCHAR(50),
    stdout LONGTEXT,
    stderr LONGTEXT,
    compile_output LONGTEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE Banners (
    id INT AUTO_INCREMENT PRIMARY KEY,
    image_data LONGTEXT,
    caption VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE Announcements (
    id INT PRIMARY KEY,
    message TEXT,
    is_active TINYINT(1) DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 8. Seed Default Essential Data
-- -----------------------------------------------------------------------------
INSERT INTO Batches (batch_name) VALUES ('Batch-1') ON DUPLICATE KEY UPDATE batch_name=batch_name;

INSERT INTO Announcements (id, message, is_active)
VALUES (1, 'Welcome to the QuizMaster Enterprise Portal', 1)
ON DUPLICATE KEY UPDATE message=VALUES(message);

-- Default Secure Admin (Initial password: Admin@QuizMaster2026 - must change on first login)
-- Hash generated via Werkzeug scrypt/pbkdf2
INSERT INTO Users (full_name, email, password_hash, role, must_change_password)
VALUES (
    'System Administrator',
    'admin@quiz.com',
    'scrypt:32768:8:1$0iA6kU3Hrhf1p9N0$c1b01c37b75225091d34c0347895ad06354673cb73d47ad8fcf32d2087593c6cfafc61559869a8449c25f4625b182054ff8325a2dfca54e2d43cbdf8b394f4b1',
    'Admin',
    0
) ON DUPLICATE KEY UPDATE role='Admin';