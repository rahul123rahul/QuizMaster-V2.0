-- QCMS Database Schema
-- Complete backend database aligned with all routes:
-- routes/auth.py, routes/quiz.py, routes/home.py,
-- routes/admin.py, routes/coordinator.py, routes/api.py,
-- routes/study_materials.py, computation.py, utils.py
-- Run this file to initialize a fresh qcms_db database.

CREATE DATABASE IF NOT EXISTS `qcms_db`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_general_ci;
USE `qcms_db`;

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- Drop tables in reverse FK order
DROP TABLE IF EXISTS `Quiz_Responses`;
DROP TABLE IF EXISTS `Quiz_Attempts`;
DROP TABLE IF EXISTS `Questions`;
DROP TABLE IF EXISTS `Quizzes`;
DROP TABLE IF EXISTS `Users`;
DROP TABLE IF EXISTS `Batches`;
DROP TABLE IF EXISTS `Banners`;
DROP TABLE IF EXISTS `Exam_Centers`;
DROP TABLE IF EXISTS `Announcements`;
DROP TABLE IF EXISTS `StudyMaterialViews`;
DROP TABLE IF EXISTS `StudyMaterialRatings`;
DROP TABLE IF EXISTS `StudyMaterialStats`;
DROP TABLE IF EXISTS `StudyMaterials`;
DROP TABLE IF EXISTS `StudyTopics`;
DROP TABLE IF EXISTS `StudyChapters`;
DROP TABLE IF EXISTS `StudySubjects`;
DROP TABLE IF EXISTS `StudyMaterialComments`;
DROP TABLE IF EXISTS `StudyMaterialBookmarks`;
DROP TABLE IF EXISTS `StudyMaterialShares`;
DROP TABLE IF EXISTS `StudyCategories`;
DROP TABLE IF EXISTS `StudyMaterialVersions`;
DROP TABLE IF EXISTS `StudyMaterialReports`;

SET FOREIGN_KEY_CHECKS = 1;

-- ============================================================
-- CORE TABLES
-- ============================================================

CREATE TABLE `Batches` (
  `batch_id` INT NOT NULL AUTO_INCREMENT,
  `batch_name` VARCHAR(100) NOT NULL,
  PRIMARY KEY (`batch_id`),
  UNIQUE KEY `uq_batches_batch_name` (`batch_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `Exam_Centers` (
  `center_id` INT NOT NULL AUTO_INCREMENT,
  `center_name` VARCHAR(255) NOT NULL,
  `city` VARCHAR(100) DEFAULT NULL,
  `address` TEXT DEFAULT NULL,
  `total_rows` INT DEFAULT 0,
  `total_cols` INT DEFAULT 0,
  `capacity` INT DEFAULT 0,
  `allocated_count` INT DEFAULT 0,
  PRIMARY KEY (`center_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `Users` (
  `user_id` INT NOT NULL AUTO_INCREMENT,
  `full_name` VARCHAR(255) NOT NULL,
  `role` ENUM('Admin','Coordinator','Student') DEFAULT 'Student',
  `email` VARCHAR(255) NOT NULL,
  `password_hash` VARCHAR(255) NOT NULL,
  `mobile` VARCHAR(20) DEFAULT NULL,
  `phone_number` VARCHAR(20) DEFAULT NULL,
  `enrolled_session` VARCHAR(100) DEFAULT NULL,
  `selected_session` VARCHAR(100) DEFAULT NULL,
  `occupation` VARCHAR(50) DEFAULT NULL,
  `college` VARCHAR(255) DEFAULT NULL,
  `department` VARCHAR(255) DEFAULT NULL,
  `section` VARCHAR(50) DEFAULT NULL,
  `study_year` VARCHAR(20) DEFAULT NULL,
  `roll_number` VARCHAR(50) DEFAULT NULL,
  `designation` VARCHAR(100) DEFAULT NULL,
  `goal_type` VARCHAR(50) DEFAULT NULL,
  `team_name` VARCHAR(100) DEFAULT NULL,
  `team_members` TEXT DEFAULT NULL,
  `is_blocked` TINYINT(1) DEFAULT 0,
  `attendance_present` INT DEFAULT 0,
  `attendance_total` INT DEFAULT 0,
  `allotted_center_id` INT DEFAULT NULL,
  `center_id` INT DEFAULT NULL,
  `seat_row` INT DEFAULT NULL,
  `seat_col` INT DEFAULT NULL,
  `avatar` TEXT DEFAULT NULL,
  `last_year_update` DATE DEFAULT NULL,
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `uq_users_email` (`email`),
  KEY `idx_users_role` (`role`),
  KEY `idx_users_batch` (`enrolled_session`),
  KEY `idx_users_department` (`department`),
  KEY `idx_users_center_id` (`center_id`),
  KEY `idx_users_allotted_center_id` (`allotted_center_id`),
  CONSTRAINT `fk_users_allotted_center`
    FOREIGN KEY (`allotted_center_id`) REFERENCES `Exam_Centers` (`center_id`)
    ON DELETE SET NULL,
  CONSTRAINT `fk_users_center`
    FOREIGN KEY (`center_id`) REFERENCES `Exam_Centers` (`center_id`)
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `Quizzes` (
  `quiz_id` INT NOT NULL AUTO_INCREMENT,
  `title` VARCHAR(255) NOT NULL,
  `marks` INT DEFAULT NULL,
  `category` VARCHAR(100) DEFAULT 'General',
  `duration_minutes` INT DEFAULT 60,
  `total_marks` INT DEFAULT 0,
  `start_time` DATETIME DEFAULT NULL,
  `instructions` TEXT DEFAULT NULL,
  `reg_status` TINYINT(1) DEFAULT 1,
  `batch` VARCHAR(100) DEFAULT NULL,
  `department` VARCHAR(255) DEFAULT NULL,
  `section` VARCHAR(50) DEFAULT NULL,
  `year` VARCHAR(20) DEFAULT NULL,
  PRIMARY KEY (`quiz_id`),
  KEY `idx_quizzes_batch` (`batch`),
  KEY `idx_quizzes_reg_status` (`reg_status`),
  KEY `idx_quizzes_start_time` (`start_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `Questions` (
  `question_id` INT NOT NULL AUTO_INCREMENT,
  `quiz_id` INT NOT NULL,
  `question_text` TEXT NOT NULL,
  `correct_option` VARCHAR(10) DEFAULT NULL,
  `marks` INT DEFAULT 1,
  `option_a` TEXT DEFAULT NULL,
  `option_b` TEXT DEFAULT NULL,
  `option_c` TEXT DEFAULT NULL,
  `option_d` TEXT DEFAULT NULL,
  `question_type` ENUM('MCQ','CODE') DEFAULT 'MCQ',
  `test_input` TEXT DEFAULT NULL,
  `test_output` TEXT DEFAULT NULL,
  `module` VARCHAR(100) DEFAULT 'General',
  `batch` VARCHAR(100) DEFAULT NULL,
  `session_title` VARCHAR(255) DEFAULT NULL,
  PRIMARY KEY (`question_id`),
  KEY `idx_questions_quiz_id` (`quiz_id`),
  KEY `idx_questions_module` (`module`),
  CONSTRAINT `fk_questions_quiz`
    FOREIGN KEY (`quiz_id`) REFERENCES `Quizzes` (`quiz_id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `Quiz_Attempts` (
  `attempt_id` INT NOT NULL AUTO_INCREMENT,
  `user_id` INT DEFAULT NULL,
  `quiz_id` INT DEFAULT NULL,
  `total_score` DECIMAL(10,2) DEFAULT 0.00,
  `status` ENUM('In-Progress','Completed','Terminated') DEFAULT 'In-Progress',
  `cheat_detected` TINYINT(1) DEFAULT 0,
  `certificate_approved` TINYINT(1) DEFAULT 0,
  `start_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `end_time` DATETIME DEFAULT NULL,
  `submitted_at` DATETIME DEFAULT NULL,
  `is_winner` TINYINT(1) DEFAULT 0,
  PRIMARY KEY (`attempt_id`),
  KEY `idx_quiz_attempts_user_id` (`user_id`),
  KEY `idx_quiz_attempts_quiz_id` (`quiz_id`),
  CONSTRAINT `fk_quiz_attempts_user`
    FOREIGN KEY (`user_id`) REFERENCES `Users` (`user_id`)
    ON DELETE SET NULL,
  CONSTRAINT `fk_quiz_attempts_quiz`
    FOREIGN KEY (`quiz_id`) REFERENCES `Quizzes` (`quiz_id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `Quiz_Responses` (
  `response_id` INT NOT NULL AUTO_INCREMENT,
  `attempt_id` INT NOT NULL,
  `question_id` INT NOT NULL,
  `selected_option` VARCHAR(50) DEFAULT NULL,
  `is_attempted` TINYINT(1) DEFAULT 0,
  `is_flagged` TINYINT(1) DEFAULT 0,
  PRIMARY KEY (`response_id`),
  UNIQUE KEY `unique_response` (`attempt_id`, `question_id`),
  KEY `idx_quiz_responses_question_id` (`question_id`),
  CONSTRAINT `fk_quiz_responses_attempt`
    FOREIGN KEY (`attempt_id`) REFERENCES `Quiz_Attempts` (`attempt_id`)
    ON DELETE CASCADE,
  CONSTRAINT `fk_quiz_responses_question`
    FOREIGN KEY (`question_id`) REFERENCES `Questions` (`question_id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `Banners` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `image_data` LONGTEXT DEFAULT NULL,
  `caption` VARCHAR(255) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `Announcements` (
  `id` INT NOT NULL,
  `message` TEXT DEFAULT NULL,
  `is_active` TINYINT(1) DEFAULT 0,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- ============================================================
-- STUDY MATERIALS TABLES
-- ============================================================

CREATE TABLE `StudySubjects` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(255) NOT NULL,
  `description` TEXT DEFAULT NULL,
  `created_by` INT DEFAULT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_study_subjects_created_by` (`created_by`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `StudyChapters` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `subject_id` INT NOT NULL,
  `name` VARCHAR(255) NOT NULL,
  `description` TEXT DEFAULT NULL,
  `created_by` INT DEFAULT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_study_chapters_subject_id` (`subject_id`),
  KEY `idx_study_chapters_created_by` (`created_by`),
  CONSTRAINT `fk_study_chapters_subject`
    FOREIGN KEY (`subject_id`) REFERENCES `StudySubjects` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `StudyTopics` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `chapter_id` INT NOT NULL,
  `name` VARCHAR(255) NOT NULL,
  `description` TEXT DEFAULT NULL,
  `tags` TEXT DEFAULT NULL,
  `created_by` INT DEFAULT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_study_topics_chapter_id` (`chapter_id`),
  KEY `idx_study_topics_created_by` (`created_by`),
  CONSTRAINT `fk_study_topics_chapter`
    FOREIGN KEY (`chapter_id`) REFERENCES `StudyChapters` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `StudyMaterials` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `topic_id` INT NOT NULL,
  `title` VARCHAR(255) NOT NULL,
  `type` VARCHAR(50) NOT NULL,
  `file_path` VARCHAR(500) DEFAULT NULL,
  `video_url` VARCHAR(500) DEFAULT NULL,
  `content` TEXT DEFAULT NULL,
  `file_size` BIGINT DEFAULT 0,
  `tags` TEXT DEFAULT NULL,
  `batch_assignment` JSON DEFAULT NULL,
  `is_public` TINYINT(1) DEFAULT 0,
  `is_featured` TINYINT(1) DEFAULT 0,
  `difficulty` VARCHAR(20) DEFAULT 'intermediate',
  `duration_minutes` INT DEFAULT 0,
  `rating` DECIMAL(3,2) DEFAULT 0,
  `rating_count` INT DEFAULT 0,
  `view_count` INT DEFAULT 0,
  `download_count` INT DEFAULT 0,
  `release_date` DATE DEFAULT NULL,
  `created_by` INT DEFAULT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `mime_type` VARCHAR(100) DEFAULT NULL,
  `original_filename` VARCHAR(255) DEFAULT NULL,
  `checksum` VARCHAR(64) DEFAULT NULL,
  `description` TEXT DEFAULT NULL,
  `ai_tags` JSON DEFAULT NULL,
  `objectives` TEXT DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_study_materials_topic_id` (`topic_id`),
  KEY `idx_study_materials_created_by` (`created_by`),
  CONSTRAINT `fk_study_materials_topic`
    FOREIGN KEY (`topic_id`) REFERENCES `StudyTopics` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `StudyMaterialStats` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `material_id` INT NOT NULL,
  `date` DATE NOT NULL,
  `downloads` INT DEFAULT 0,
  `views` INT DEFAULT 0,
  `unique_viewers` INT DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `idx_study_material_stats_material_id` (`material_id`),
  KEY `idx_study_material_stats_date` (`date`),
  CONSTRAINT `fk_study_material_stats_material`
    FOREIGN KEY (`material_id`) REFERENCES `StudyMaterials` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `StudyMaterialRatings` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `material_id` INT NOT NULL,
  `user_id` INT NOT NULL,
  `rating` INT NOT NULL,
  `comment` TEXT DEFAULT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_user_material_rating` (`material_id`, `user_id`),
  KEY `idx_study_material_ratings_material_id` (`material_id`),
  KEY `idx_study_material_ratings_user_id` (`user_id`),
  CONSTRAINT `fk_study_material_ratings_material`
    FOREIGN KEY (`material_id`) REFERENCES `StudyMaterials` (`id`)
    ON DELETE CASCADE,
  CONSTRAINT `fk_study_material_ratings_user`
    FOREIGN KEY (`user_id`) REFERENCES `Users` (`user_id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `StudyMaterialViews` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `material_id` INT NOT NULL,
  `user_id` INT NOT NULL,
  `viewed_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_study_material_views_material_id` (`material_id`),
  KEY `idx_study_material_views_user_id` (`user_id`),
  CONSTRAINT `fk_study_material_views_material`
    FOREIGN KEY (`material_id`) REFERENCES `StudyMaterials` (`id`)
    ON DELETE CASCADE,
  CONSTRAINT `fk_study_material_views_user`
    FOREIGN KEY (`user_id`) REFERENCES `Users` (`user_id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `StudyMaterialComments` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `material_id` INT NOT NULL,
  `user_id` INT NOT NULL,
  `content` TEXT DEFAULT NULL,
  `rating` INT DEFAULT NULL,
  `parent_id` INT DEFAULT NULL,
  `is_approved` TINYINT(1) DEFAULT 1,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_study_material_comments_material_id` (`material_id`),
  KEY `idx_study_material_comments_user_id` (`user_id`),
  KEY `idx_study_material_comments_parent_id` (`parent_id`),
  CONSTRAINT `fk_study_material_comments_material`
    FOREIGN KEY (`material_id`) REFERENCES `StudyMaterials` (`id`)
    ON DELETE CASCADE,
  CONSTRAINT `fk_study_material_comments_user`
    FOREIGN KEY (`user_id`) REFERENCES `Users` (`user_id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `StudyMaterialBookmarks` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `material_id` INT NOT NULL,
  `user_id` INT NOT NULL,
  `note` TEXT DEFAULT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_bookmark` (`material_id`, `user_id`),
  KEY `idx_study_material_bookmarks_material_id` (`material_id`),
  KEY `idx_study_material_bookmarks_user_id` (`user_id`),
  CONSTRAINT `fk_study_material_bookmarks_material`
    FOREIGN KEY (`material_id`) REFERENCES `StudyMaterials` (`id`)
    ON DELETE CASCADE,
  CONSTRAINT `fk_study_material_bookmarks_user`
    FOREIGN KEY (`user_id`) REFERENCES `Users` (`user_id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `StudyMaterialShares` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `material_id` INT NOT NULL,
  `share_token` VARCHAR(100) NOT NULL,
  `access_type` VARCHAR(20) DEFAULT 'private',
  `expires_at` DATETIME DEFAULT NULL,
  `max_downloads` INT DEFAULT NULL,
  `share_password` VARCHAR(255) DEFAULT NULL,
  `download_count` INT DEFAULT 0,
  `created_by` INT DEFAULT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_share_token` (`share_token`),
  KEY `idx_study_material_shares_material_id` (`material_id`),
  CONSTRAINT `fk_study_material_shares_material`
    FOREIGN KEY (`material_id`) REFERENCES `StudyMaterials` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `StudyCategories` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(255) NOT NULL,
  `parent_id` INT DEFAULT NULL,
  `description` TEXT DEFAULT NULL,
  `icon` VARCHAR(50) DEFAULT NULL,
  `color` VARCHAR(20) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_study_categories_parent_id` (`parent_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `StudyMaterialVersions` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `material_id` INT NOT NULL,
  `version_number` INT NOT NULL,
  `file_path` VARCHAR(500) DEFAULT NULL,
  `file_size` BIGINT DEFAULT 0,
  `checksum` VARCHAR(64) DEFAULT NULL,
  `changes` TEXT DEFAULT NULL,
  `created_by` INT DEFAULT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_study_material_versions_material_id` (`material_id`),
  CONSTRAINT `fk_study_material_versions_material`
    FOREIGN KEY (`material_id`) REFERENCES `StudyMaterials` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `StudyMaterialReports` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `material_id` INT NOT NULL,
  `user_id` INT NOT NULL,
  `reason` VARCHAR(255) DEFAULT NULL,
  `description` TEXT DEFAULT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_study_material_reports_material_id` (`material_id`),
  KEY `idx_study_material_reports_user_id` (`user_id`),
  CONSTRAINT `fk_study_material_reports_material`
    FOREIGN KEY (`material_id`) REFERENCES `StudyMaterials` (`id`)
    ON DELETE CASCADE,
  CONSTRAINT `fk_study_material_reports_user`
    FOREIGN KEY (`user_id`) REFERENCES `Users` (`user_id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- ============================================================
-- DEFAULT DATA
-- ============================================================

INSERT INTO `Users` (`full_name`, `role`, `email`, `password_hash`)
VALUES ('System Admin', 'Admin', 'admin@quiz.com', 'admin123');

INSERT INTO `Announcements` (`id`, `message`, `is_active`)
VALUES (1, 'Welcome to the Quiz Portal', 1);