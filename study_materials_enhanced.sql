-- Enhanced Study Materials Database Schema
-- Execute this to upgrade Study Material feature

-- Create new tables for enhanced functionality

-- 1. Material Categories (for organization)
CREATE TABLE IF NOT EXISTS StudyCategories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    parent_id INT NULL,
    description TEXT,
    icon VARCHAR(50),
    color VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_id) REFERENCES StudyCategories(id)
);

-- 2. Enhanced Materials Table (extends StudyMaterials)
ALTER TABLE StudyMaterials ADD COLUMN IF NOT EXISTS category_id INT NULL;
ALTER TABLE StudyMaterials ADD COLUMN IF NOT EXISTS difficulty ENUM('beginner', 'intermediate', 'advanced', 'expert') DEFAULT 'intermediate';
ALTER TABLE StudyMaterials ADD COLUMN IF NOT EXISTS duration_minutes INT;
ALTER TABLE StudyMaterials ADD COLUMN IF NOT EXISTSai_tags JSON;  -- AI-generated tags
ALTER TABLE StudyMaterials ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE StudyMaterials ADD COLUMN IF NOT EXISTS objectives JSON;  -- Learning objectives
ALTER TABLE StudyMaterials ADD COLUMN IF NOT EXISTS is_featured BOOLEAN DEFAULT FALSE;
ALTER TABLE StudyMaterials ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE;
ALTER TABLE StudyMaterials ADD COLUMN IF NOT EXISTS view_count INT DEFAULT 0;
ALTER TABLE StudyMaterials ADD COLUMN IF NOT EXISTS download_count INT DEFAULT 0;
ALTER TABLE StudyMaterials ADD COLUMN IF NOT EXISTS rating DECIMAL(3,2) DEFAULT 0;
ALTER TABLE StudyMaterials ADD COLUMN IF NOT EXISTS rating_count INT DEFAULT 0;
ALTER TABLE StudyMaterials ADD COLUMN IF NOT EXISTS checksum VARCHAR(64);  -- File integrity check
ALTER TABLE StudyMaterials ADD COLUMN IF NOT EXISTS mime_type VARCHAR(100);
ALTER TABLE StudyMaterials ADD COLUMN IF NOT EXISTS original_filename VARCHAR(255);

-- 3. Material Versions (version control)
CREATE TABLE IF NOT EXISTS StudyMaterialVersions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    material_id INT NOT NULL,
    version_number INT NOT NULL,
    file_path VARCHAR(500),
    file_size INT,
    checksum VARCHAR(64),
    changes TEXT,
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (material_id) REFERENCES StudyMaterials(id),
    FOREIGN KEY (created_by) REFERENCES Users(user_id)
);

-- 4. Material Comments & Reviews
CREATE TABLE IF NOT EXISTS StudyMaterialComments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    material_id INT NOT NULL,
    user_id INT NOT NULL,
    parent_id INT NULL,
    content TEXT NOT NULL,
    rating INT,  -- 1-5 stars
    is_approved BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (material_id) REFERENCES StudyMaterials(id),
    FOREIGN KEY (user_id) REFERENCES Users(user_id),
    FOREIGN KEY (parent_id) REFERENCES StudyMaterialComments(id)
);

-- 5. Material Sharing & Expiry
CREATE TABLE IF NOT EXISTS StudyMaterialShares (
    id INT AUTO_INCREMENT PRIMARY KEY,
    material_id INT NOT NULL,
    share_token VARCHAR(64) NOT NULL UNIQUE,
    access_type ENUM('public', 'private', 'expiring') DEFAULT 'private',
    password_protected BOOLEAN DEFAULT FALSE,
    share_password VARCHAR(255),
    expires_at DATETIME,
    max_downloads INT,
    download_count INT DEFAULT 0,
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (material_id) REFERENCES StudyMaterials(id),
    FOREIGN KEY (created_by) REFERENCES Users(user_id)
);

-- 6. Analytics - Daily material stats
CREATE TABLE IF NOT EXISTS StudyMaterialStats (
    id INT AUTO_INCREMENT PRIMARY KEY,
    material_id INT NOT NULL,
    date DATE NOT NULL,
    views INT DEFAULT 0,
    downloads INT DEFAULT 0,
    unique_viewers INT DEFAULT 0,
    avg_watch_time INT DEFAULT 0,  -- seconds for video
    FOREIGN KEY (material_id) REFERENCES StudyMaterials(id),
    UNIQUE KEY unique_date_material (material_id, date)
);

-- 7. Bulk Upload Sessions
CREATE TABLE IF NOT EXISTS StudyBulkUploads (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_token VARCHAR(64) NOT NULL UNIQUE,
    status ENUM('pending', 'processing', 'completed', 'failed') DEFAULT 'pending',
    total_files INT DEFAULT 0,
    processed_files INT DEFAULT 0,
    failed_files INT DEFAULT 0,
    error_log JSON,
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    FOREIGN KEY (created_by) REFERENCES Users(user_id)
);

-- 8. Upload Chunks (for resumable uploads)
CREATE TABLE IF NOT EXISTS StudyUploadChunks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    upload_id VARCHAR(64) NOT NULL,
    chunk_number INT NOT NULL,
    chunk_data LONGBLOB,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_chunk (upload_id, chunk_number)
);

-- 9. Material Bookmarks
CREATE TABLE IF NOT EXISTS StudyMaterialBookmarks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    material_id INT NOT NULL,
    user_id INT NOT NULL,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (material_id) REFERENCES StudyMaterials(id),
    FOREIGN KEY (user_id) REFERENCES Users(user_id),
    UNIQUE KEY unique_bookmark (material_id, user_id)
);

-- 10. Material Reports (for flags/abuse)
CREATE TABLE IF NOT EXISTS StudyMaterialReports (
    id INT AUTO_INCREMENT PRIMARY KEY,
    material_id INT NOT NULL,
    user_id INT NOT NULL,
    reason ENUM('copyright', 'inappropriate', 'incorrect', 'broken_link', 'other') NOT NULL,
    description TEXT,
    status ENUM('pending', 'reviewed', 'resolved', 'rejected') DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (material_id) REFERENCES StudyMaterials(id),
    FOREIGN KEY (user_id) REFERENCES Users(user_id)
);

-- Create additional indexes for performance
CREATE INDEX idx_materials_difficulty ON StudyMaterials(difficulty);
CREATE INDEX idx_materials_featured ON StudyMaterials(is_featured);
CREATE INDEX idx_materials_category ON StudyMaterials(category_id);
CREATE INDEX idx_material_versions ON StudyMaterialVersions(material_id, version_number);
CREATE INDEX idx_material_stats_date ON StudyMaterialStats(date);
CREATE INDEX idx_bulk_uploads_token ON StudyBulkUploads(session_token);
CREATE INDEX idx_shares_token ON StudyMaterialShares(share_token);

-- Insert default categories
INSERT INTO StudyCategories (name, description, icon, color) VALUES 
('Notes', 'Lecture notes and handouts', 'fa-sticky-note', '#4f46e5'),
('Videos', 'Video tutorials', 'fa-video', '#0ea5e9'),
('Presentations', 'Slides and presentations', 'fa-chalkboard-teacher', '#f59e0b'),
('Question Papers', 'Previous year papers', 'fa-file-alt', '#10b981'),
('Books', 'E-books and references', 'fa-book', '#8b5cf6'),
('Assignments', 'Practice problems', 'fa-pencil-alt', '#ef4444')
ON DUPLICATE KEY UPDATE name=name;