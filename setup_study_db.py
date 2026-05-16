import pymysql
from database import get_db_connection

print("Setting up Study Materials tables...")

conn = get_db_connection()
try:
    with conn.cursor() as cursor:
        # StudySubjects table
        print("Creating StudySubjects table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS StudySubjects (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                created_by INT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("StudySubjects table ready")
        
        # StudyChapters table
        print("Creating StudyChapters table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS StudyChapters (
                id INT AUTO_INCREMENT PRIMARY KEY,
                subject_id INT NOT NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                created_by INT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (subject_id) REFERENCES StudySubjects(id) ON DELETE CASCADE
            )
        """)
        print("StudyChapters table ready")
        
        # StudyTopics table
        print("Creating StudyTopics table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS StudyTopics (
                id INT AUTO_INCREMENT PRIMARY KEY,
                chapter_id INT NOT NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                tags TEXT,
                created_by INT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chapter_id) REFERENCES StudyChapters(id) ON DELETE CASCADE
            )
        """)
        print("StudyTopics table ready")
        
        # StudyMaterials table
        print("Creating StudyMaterials table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS StudyMaterials (
                id INT AUTO_INCREMENT PRIMARY KEY,
                topic_id INT NOT NULL,
                title VARCHAR(255) NOT NULL,
                type VARCHAR(50) NOT NULL,
                file_path VARCHAR(500),
                video_url VARCHAR(500),
                content TEXT,
                file_size BIGINT DEFAULT 0,
                tags TEXT,
                batch_assignment JSON,
                is_public TINYINT DEFAULT 0,
                is_featured TINYINT DEFAULT 0,
                difficulty VARCHAR(20) DEFAULT 'intermediate',
                duration_minutes INT DEFAULT 0,
                rating DECIMAL(3,2) DEFAULT 0,
                rating_count INT DEFAULT 0,
                view_count INT DEFAULT 0,
                download_count INT DEFAULT 0,
                release_date DATE,
                created_by INT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (topic_id) REFERENCES StudyTopics(id) ON DELETE CASCADE
            )
        """)
        
        try:
            cursor.execute("ALTER TABLE StudyMaterials ADD COLUMN difficulty VARCHAR(20) DEFAULT 'intermediate'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE StudyMaterials ADD COLUMN is_featured TINYINT DEFAULT 0")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE StudyMaterials ADD COLUMN duration_minutes INT DEFAULT 0")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE StudyMaterials ADD COLUMN rating DECIMAL(3,2) DEFAULT 0")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE StudyMaterials ADD COLUMN rating_count INT DEFAULT 0")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE StudyMaterials ADD COLUMN view_count INT DEFAULT 0")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE StudyMaterials ADD COLUMN download_count INT DEFAULT 0")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE StudyMaterials ADD COLUMN mime_type VARCHAR(100)")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE StudyMaterials ADD COLUMN original_filename VARCHAR(255)")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE StudyMaterials ADD COLUMN checksum VARCHAR(64)")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE StudyMaterials ADD COLUMN description TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE StudyMaterials ADD COLUMN ai_tags JSON")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE StudyMaterials ADD COLUMN objectives TEXT")
        except:
            pass
        
        print("StudyMaterials table ready")
        
        # StudyMaterialStats table
        print("Creating StudyMaterialStats table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS StudyMaterialStats (
                id INT AUTO_INCREMENT PRIMARY KEY,
                material_id INT NOT NULL,
                date DATE NOT NULL,
                downloads INT DEFAULT 0,
                views INT DEFAULT 0,
                unique_viewers INT DEFAULT 0,
                FOREIGN KEY (material_id) REFERENCES StudyMaterials(id) ON DELETE CASCADE
            )
        """)
        print("StudyMaterialStats table ready")
        
        # StudyMaterialRatings table
        print("Creating StudyMaterialRatings table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS StudyMaterialRatings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                material_id INT NOT NULL,
                user_id INT NOT NULL,
                rating INT NOT NULL,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (material_id) REFERENCES StudyMaterials(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE CASCADE,
                UNIQUE KEY unique_user_material (material_id, user_id)
            )
        """)
        try:
            cursor.execute("ALTER TABLE StudyMaterialRatings ADD COLUMN comment TEXT")
        except:
            pass
        print("StudyMaterialRatings table ready")
        
        # StudyMaterialViews table
        print("Creating StudyMaterialViews table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS StudyMaterialViews (
                id INT AUTO_INCREMENT PRIMARY KEY,
                material_id INT NOT NULL,
                user_id INT NOT NULL,
                viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (material_id) REFERENCES StudyMaterials(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE CASCADE
            )
        """)
        print("StudyMaterialViews table ready")
        
    conn.commit()
    print("All Study Materials tables created successfully!")
    print("Restart your Flask app and try again.")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
