from database import get_db_connection

class ComputationEngine:
    
    def mark_question(self, attempt_id, question_id, option):
        """
        Updates response. If option is None, it remains skipped (Orange).
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        
        is_attempted = True if option else False
        
        # Upsert Logic (Insert if new, Update if exists)
        sql = """
        INSERT INTO Quiz_Responses (attempt_id, question_id, selected_option, is_attempted)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE 
            selected_option = VALUES(selected_option),
            is_attempted = VALUES(is_attempted)
        """
        cursor.execute(sql, (attempt_id, question_id, option, is_attempted))
        conn.commit()
        conn.close()
        return is_attempted

    def get_palette_status(self, attempt_id):
        """
        Returns dictionary of question_ids and their color status.
        """
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        sql = "SELECT question_id, is_attempted FROM Quiz_Responses WHERE attempt_id = %s"
        cursor.execute(sql, (attempt_id,))
        results = cursor.fetchall()
        conn.close()
        
        # Format: {1: 'green', 2: 'orange'}
        palette = {}
        for row in results:
            palette[row['question_id']] = 'green' if row['is_attempted'] else 'orange'
        return palette

    def calculate_score(self, attempt_id):
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Calculate Total Score
        sql = """
        SELECT SUM(q.marks) 
        FROM Quiz_Responses r
        JOIN Questions q ON r.question_id = q.question_id
        WHERE r.attempt_id = %s AND r.selected_option = q.correct_option
        """
        cursor.execute(sql, (attempt_id,))
        score = cursor.fetchone()[0] or 0
        
        # Update Attempt Table
        update_sql = "UPDATE Quiz_Attempts SET total_score = %s, status = 'Completed', end_time = NOW() WHERE attempt_id = %s"
        cursor.execute(update_sql, (score, attempt_id))
        
        conn.commit()
        conn.close()
        return score