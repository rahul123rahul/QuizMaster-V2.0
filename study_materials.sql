-- Study Materials Database Schema
-- Execute this to setup Study Material feature

CREATE TABLE IF NOT EXISTS StudySubjects (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES Users(user_id)
);

CREATE TABLE IF NOT EXISTS StudyChapters (
    id INT AUTO_INCREMENT PRIMARY KEY,
    subject_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subject_id) REFERENCES StudySubjects(id),
    FOREIGN KEY (created_by) REFERENCES Users(user_id)
);

CREATE TABLE IF NOT EXISTS StudyTopics (
    id INT AUTO_INCREMENT PRIMARY KEY,
    chapter_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    tags JSON,
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chapter_id) REFERENCES StudyChapters(id),
    FOREIGN KEY (created_by) REFERENCES Users(user_id)
);

CREATE TABLE IF NOT EXISTS StudyMaterials (
    id INT AUTO_INCREMENT PRIMARY KEY,
    topic_id INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    type ENUM('pdf', 'docx', 'pptx', 'video', 'notes') NOT NULL,
    file_path VARCHAR(500),
    video_url VARCHAR(500),
    content TEXT,
    file_size INT,
    tags JSON,
    batch_assignment JSON,  -- {"batch1": true, "batch2": false}
    is_public BOOLEAN DEFAULT FALSE,
    release_date DATETIME,
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (topic_id) REFERENCES StudyTopics(id),
    FOREIGN KEY (created_by) REFERENCES Users(user_id)
);

CREATE TABLE IF NOT EXISTS StudyMaterialViews (
    id INT AUTO_INCREMENT PRIMARY KEY,
    material_id INT NOT NULL,
    user_id INT,
    viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (material_id) REFERENCES StudyMaterials(id),
    FOREIGN KEY (user_id) REFERENCES Users(user_id)
);

-- Indexes for performance
CREATE INDEX idx_materials_topic ON StudyMaterials(topic_id);
CREATE INDEX idx_materials_batch ON StudyMaterials(batch_assignment);
CREATE INDEX idx_views_material ON StudyMaterialViews(material_id);
CREATE INDEX idx_views_user ON StudyMaterialViews(user_id);

-- Sample data
INSERT INTO StudySubjects (name, description, created_by) VALUES 
('Mathematics', 'Mathematics study materials', 1),
('Physics', 'Physics study materials', 1);

INSERT INTO StudyChapters (subject_id, name, description, created_by) VALUES 
(1, 'Calculus', 'Differential and Integral Calculus', 1),
(1, 'Algebra', 'Linear Algebra and Matrices', 1);

INSERT INTO StudyTopics (chapter_id, name, tags, created_by) VALUES 
(1, 'Limits', '["important", "exam-focused"]', 1),
(1, 'Derivatives', '["important"]', 1);

-- Trigger for auto-indexing
DELIMITER //
CREATE TRIGGER update_batch_index BEFORE INSERT ON StudyMaterials
FOR EACH ROW
BEGIN
    IF NEW.batch_assignment IS NULL THEN
        SET NEW.batch_assignment = JSON_OBJECT();
    END IF;
END//
DELIMITER ;

