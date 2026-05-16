-- DATABASE INITIALIZATION SCRIPT
-- Run this to create an empty database structure

SET FOREIGN_KEY_CHECKS = 0;

-- 1. DROP EXISTING TABLES (Clean Slate - in correct order for foreign keys)
DROP TABLE IF EXISTS Quiz_Responses;
DROP TABLE IF EXISTS Quiz_Attempts;
DROP TABLE IF EXISTS Questions;
DROP TABLE IF EXISTS Quizzes;
DROP TABLE IF EXISTS Users;
DROP TABLE IF EXISTS Batches;
DROP TABLE IF EXISTS Banners;
DROP TABLE IF EXISTS Exam_Centers;
DROP TABLE IF EXISTS Announcements;

SET FOREIGN_KEY_CHECKS = 1;

-- Also drop columns if they exist (for AI enhancement)
-- These are commented because they may cause errors if columns already exist
-- Run manually if needed: ALTER TABLE Questions ADD COLUMN batch VARCHAR(100);

-- 2. CREATE TABLES

-- Table: Batches
CREATE TABLE Batches (
    batch_id INT AUTO_INCREMENT PRIMARY KEY,
    batch_name VARCHAR(100) NOT NULL UNIQUE
);

-- Table: Exam_Centers
CREATE TABLE Exam_Centers (
    center_id INT AUTO_INCREMENT PRIMARY KEY,
    center_name VARCHAR(255) NOT NULL,
    city VARCHAR(100),
    address TEXT,
    total_rows INT DEFAULT 0,
    total_cols INT DEFAULT 0,
    capacity INT DEFAULT 0,
    allocated_count INT DEFAULT 0
);

-- Table: Users
CREATE TABLE Users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    mobile VARCHAR(20),
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('Student', 'Admin', 'Coordinator') DEFAULT 'Student',
    
    -- Student Details
    enrolled_session VARCHAR(100), -- Links to Batches.batch_name usually
    occupation VARCHAR(50),
    college VARCHAR(255),
    department VARCHAR(100),
    section VARCHAR(50),
    study_year VARCHAR(20),
    roll_number VARCHAR(50),
    designation VARCHAR(100),
    
    -- Team Details
    goal_type VARCHAR(50),
    team_name VARCHAR(100),
    team_members TEXT,
    
    -- Security & Attendance
    is_blocked TINYINT(1) DEFAULT 0,
    attendance_present INT DEFAULT 0,
    attendance_total INT DEFAULT 0,
    
    -- Center Allocation
    allotted_center_id INT,
    center_id INT, -- Redundant in code, keeping for compatibility
    seat_row INT,
    seat_col INT,
    
    FOREIGN KEY (allotted_center_id) REFERENCES Exam_Centers(center_id) ON DELETE SET NULL
);

-- Table: Quizzes (Sessions)
CREATE TABLE Quizzes (
    quiz_id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    duration_minutes INT DEFAULT 60,
    total_marks INT DEFAULT 0, -- Often used as 'Certificate Status' (1=Enabled) in your app
    start_time DATETIME,
    instructions TEXT,
    reg_status TINYINT(1) DEFAULT 1,
    
    -- Filters
    batch VARCHAR(100),
    department VARCHAR(100),
    section VARCHAR(50),
    year VARCHAR(20)
);

-- Table: Questions
CREATE TABLE Questions (
    question_id INT AUTO_INCREMENT PRIMARY KEY,
    quiz_id INT NOT NULL,
    question_type ENUM('MCQ', 'CODE') DEFAULT 'MCQ',
    question_text TEXT NOT NULL,
    
    -- MCQ Options
    option_a TEXT,
    option_b TEXT,
    option_c TEXT,
    option_d TEXT,
    correct_option VARCHAR(10), -- 'A', 'B', 'C', 'D'
    
    -- Coding Options
    test_input TEXT,
    test_output TEXT,
    
    marks INT DEFAULT 1,
    module VARCHAR(100) DEFAULT 'General',
    
    FOREIGN KEY (quiz_id) REFERENCES Quizzes(quiz_id) ON DELETE CASCADE
);

-- Add batch/session fields to Questions for AI enhancement (run separately if needed)
-- ALTER TABLE Questions ADD COLUMN batch VARCHAR(100) AFTER module;
-- ALTER TABLE Questions ADD COLUMN session_title VARCHAR(255) AFTER batch;

-- Table: Quiz_Attempts
CREATE TABLE Quiz_Attempts (
    attempt_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    quiz_id INT,
    total_score FLOAT DEFAULT 0,
    status ENUM('In-Progress', 'Completed', 'Terminated') DEFAULT 'In-Progress',
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_time DATETIME,
    certificate_approved TINYINT(1) DEFAULT 0,
    
    FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE SET NULL,
    FOREIGN KEY (quiz_id) REFERENCES Quizzes(quiz_id) ON DELETE CASCADE
);

-- Table: Quiz_Responses
CREATE TABLE Quiz_Responses (
    response_id INT AUTO_INCREMENT PRIMARY KEY,
    attempt_id INT NOT NULL,
    question_id INT NOT NULL,
    selected_option TEXT,
    is_attempted TINYINT(1) DEFAULT 0,
    
    UNIQUE KEY unique_response (attempt_id, question_id),
    FOREIGN KEY (attempt_id) REFERENCES Quiz_Attempts(attempt_id) ON DELETE CASCADE,
    FOREIGN KEY (question_id) REFERENCES Questions(question_id) ON DELETE CASCADE
);

-- Table: Banners
CREATE TABLE Banners (
    id INT AUTO_INCREMENT PRIMARY KEY,
    image_data LONGTEXT, -- Stores Base64 string
    caption VARCHAR(255)
);

-- Table: Announcements
CREATE TABLE Announcements (
    id INT PRIMARY KEY,
    message TEXT,
    is_active TINYINT(1) DEFAULT 0
);

-- 3. INSERT DEFAULT DATA

-- Default Admin (Password: admin123) - You should change this immediately
-- Note: In production, use hashed passwords. This is a placeholder.
INSERT INTO Users (full_name, email, password_hash, role) 
VALUES ('System Admin', 'admin@quiz.com', 'admin123', 'Admin');

-- Initialize Announcement Row
INSERT INTO Announcements (id, message, is_active) VALUES (1, 'Welcome to the Quiz Portal', 1);