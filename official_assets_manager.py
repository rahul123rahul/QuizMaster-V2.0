import os
import io
import uuid
import re
import json
from datetime import datetime
from werkzeug.utils import secure_filename
from database import get_db_connection

# Upload Configuration
ASSET_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads', 'official_assets')
os.makedirs(ASSET_UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'svg'}
ALLOWED_MIME_TYPES = {
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/jpg': 'jpg',
    'image/webp': 'webp',
    'image/svg+xml': 'svg'
}
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
VALID_ASSET_TYPES = {'program_director_signature', 'official_seal'}

def get_client_ip(req=None):
    if not req:
        return '127.0.0.1'
    forwarded = req.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return req.remote_addr or '127.0.0.1'

def log_admin_action(user_id, action, details=None, req=None):
    """Logs administrative operations into audit_logs table."""
    conn = get_db_connection()
    if not conn:
        return
    try:
        ip = get_client_ip(req)
        user_agent = req.headers.get('User-Agent', '')[:255] if req else ''
        details_str = json.dumps(details) if isinstance(details, (dict, list)) else (str(details) if details else None)
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO audit_logs (user_id, action, ip_address, user_agent, details)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, action, ip, user_agent, details_str))
        conn.commit()
    except Exception as e:
        print(f"Failed to log admin action: {e}")
    finally:
        conn.close()

def validate_svg_content(content_bytes):
    """Validates SVG safely to prevent XSS / XML External Entity attacks."""
    try:
        text = content_bytes.decode('utf-8', errors='ignore').lower()
    except Exception:
        return False, "Could not decode SVG file as UTF-8"

    # Block malicious patterns
    dangerous_patterns = [
        r'<script',
        r'javascript:',
        r'<!entity',
        r'<!doctype.*system',
        r'href\s*=\s*["\']\s*data:',
        r'onload\s*=',
        r'onerror\s*=',
        r'<iframe',
        r'<foreignobject'
    ]
    for pat in dangerous_patterns:
        if re.search(pat, text):
            return False, f"SVG contains disallowed dangerous vector: {pat}"

    # Verify root or basic svg tag exists
    if '<svg' not in text or '</svg>' not in text:
        return False, "Invalid SVG format: missing <svg> tags"

    return True, None

def validate_raster_image(content_bytes, ext):
    """Validates raster image integrity and format using Pillow."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(content_bytes))
        img.verify()

        # Reopen to check dimensions (verify() invalidates image object)
        img = Image.open(io.BytesIO(content_bytes))
        width, height = img.size
        if width <= 0 or height <= 0:
            return False, "Invalid image dimensions"

        return True, None
    except Exception as e:
        return False, f"Corrupt or invalid image file: {str(e)}"

def validate_asset_file(file_storage):
    """
    Validates file extension, size, MIME type, and content integrity.
    Returns (is_valid, error_message, content_bytes, clean_ext, mime_type)
    """
    if not file_storage or not file_storage.filename:
        return False, "No file selected", None, None, None

    filename = secure_filename(file_storage.filename)
    parts = filename.rsplit('.', 1)
    if len(parts) < 2:
        return False, "File must have a valid extension (.png, .jpg, .jpeg, .webp, .svg)", None, None, None

    ext = parts[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Disallowed file extension '.{ext}'. Allowed types: PNG, JPG, JPEG, WEBP, SVG", None, None, None

    # Read bytes safely
    content_bytes = file_storage.read()
    file_size = len(content_bytes)

    if file_size == 0:
        return False, "Uploaded file is empty", None, None, None

    if file_size > MAX_FILE_SIZE_BYTES:
        return False, f"File size exceeds maximum limit of 5MB (size: {file_size / (1024*1024):.2f}MB)", None, None, None

    # Determine MIME type
    mime_type = getattr(file_storage, 'mimetype', '') or getattr(file_storage, 'content_type', '')
    if ext == 'svg':
        mime_type = 'image/svg+xml'
    elif ext in ['jpg', 'jpeg']:
        mime_type = 'image/jpeg'
    elif ext == 'png':
        mime_type = 'image/png'
    elif ext == 'webp':
        mime_type = 'image/webp'

    # Deep validation
    if ext == 'svg':
        valid, msg = validate_svg_content(content_bytes)
        if not valid:
            return False, msg, None, None, None
    else:
        valid, msg = validate_raster_image(content_bytes, ext)
        if not valid:
            return False, msg, None, None, None

    return True, None, content_bytes, ext, mime_type

def upload_official_asset(asset_type, file_storage, uploaded_by=None, req=None, auto_activate=True):
    """
    Saves an official signature or seal asset and registers in the DB.
    Enforces the rule: Exactly one active asset of each type at a time.
    """
    if asset_type not in VALID_ASSET_TYPES:
        return {'success': False, 'message': f"Invalid asset type '{asset_type}'"}

    valid, err, content_bytes, ext, mime_type = validate_asset_file(file_storage)
    if not valid:
        return {'success': False, 'message': err}

    original_name = secure_filename(file_storage.filename)
    unique_filename = f"{asset_type}_{uuid.uuid4().hex[:16]}.{ext}"
    physical_path = os.path.join(ASSET_UPLOAD_DIR, unique_filename)
    web_path = f"/static/uploads/official_assets/{unique_filename}"
    file_size = len(content_bytes)

    # Save physical file
    try:
        with open(physical_path, 'wb') as f:
            f.write(content_bytes)
    except Exception as e:
        return {'success': False, 'message': f"Failed to write file to disk: {str(e)}"}

    conn = get_db_connection()
    if not conn:
        if os.path.exists(physical_path):
            os.remove(physical_path)
        return {'success': False, 'message': "Database connection unavailable"}

    asset_id = None
    try:
        with conn.cursor() as cursor:
            # Check duplicate by checking active identical file size and original name
            cursor.execute("""
                SELECT id FROM official_assets
                WHERE asset_type=%s AND original_file_name=%s AND file_size=%s
            """, (asset_type, original_name, file_size))
            dup = cursor.fetchone()
            if dup:
                # Remove newly written file to avoid orphaned storage
                if os.path.exists(physical_path):
                    os.remove(physical_path)
                return {'success': False, 'message': f"An identical {asset_type.replace('_', ' ')} with the same name and size already exists."}

            # If auto_activate, deactivate any currently active asset of this type
            if auto_activate:
                cursor.execute("""
                    UPDATE official_assets SET is_active=0 WHERE asset_type=%s
                """, (asset_type,))

            is_active_val = 1 if auto_activate else 0
            cursor.execute("""
                INSERT INTO official_assets (
                    asset_type, file_path, original_file_name, mime_type,
                    file_size, is_active, uploaded_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (asset_type, web_path, original_name, mime_type, file_size, is_active_val, uploaded_by))
            asset_id = cursor.lastrowid

        conn.commit()

        # Audit log
        log_admin_action(
            uploaded_by,
            'ASSET_UPLOAD',
            {'asset_id': asset_id, 'asset_type': asset_type, 'filename': original_name, 'active': auto_activate},
            req
        )

        return {
            'success': True,
            'message': f"{asset_type.replace('_', ' ').title()} uploaded successfully!",
            'asset_id': asset_id,
            'file_path': web_path,
            'is_active': auto_activate
        }
    except Exception as e:
        conn.rollback()
        if os.path.exists(physical_path):
            os.remove(physical_path)
        return {'success': False, 'message': f"Database error during upload: {str(e)}"}
    finally:
        conn.close()

def get_official_assets(asset_type=None):
    """Retrieves all assets, optionally filtered by asset_type."""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cursor:
            if asset_type:
                cursor.execute("""
                    SELECT a.*, u.full_name as uploader_name
                    FROM official_assets a
                    LEFT JOIN Users u ON a.uploaded_by = u.user_id
                    WHERE a.asset_type = %s
                    ORDER BY a.is_active DESC, a.created_at DESC
                """, (asset_type,))
            else:
                cursor.execute("""
                    SELECT a.*, u.full_name as uploader_name
                    FROM official_assets a
                    LEFT JOIN Users u ON a.uploaded_by = u.user_id
                    ORDER BY a.asset_type, a.is_active DESC, a.created_at DESC
                """)
            rows = cursor.fetchall()
            for r in rows:
                if isinstance(r.get('created_at'), datetime):
                    r['created_at_formatted'] = r['created_at'].strftime('%b %d, %Y %I:%M %p')
                if isinstance(r.get('updated_at'), datetime):
                    r['updated_at_formatted'] = r['updated_at'].strftime('%b %d, %Y %I:%M %p')
                r['file_size_formatted'] = f"{r['file_size'] / 1024:.1f} KB" if r.get('file_size') else "0 KB"
            return rows
    finally:
        conn.close()

def get_active_official_asset(asset_type):
    """
    Retrieves the currently active asset for the specified asset_type.
    Returns asset dict with 'full_path' resolving to absolute filesystem location, or None.
    Reusable by certificates, result documents, and reports.
    """
    if asset_type not in VALID_ASSET_TYPES:
        return None

    conn = get_db_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM official_assets
                WHERE asset_type=%s AND is_active=1
                LIMIT 1
            """, (asset_type,))
            asset = cursor.fetchone()
            if not asset:
                return None

            # Calculate absolute filesystem path
            web_path = asset.get('file_path', '')
            filename = os.path.basename(web_path)
            full_path = os.path.join(ASSET_UPLOAD_DIR, filename)

            if os.path.exists(full_path):
                asset['full_path'] = full_path
                return asset
            else:
                return None
    finally:
        conn.close()

def set_official_asset_active(asset_id, is_active, admin_user_id=None, req=None):
    """
    Enables or disables an asset.
    When activating, automatically deactivates all other assets of the same type.
    """
    conn = get_db_connection()
    if not conn:
        return {'success': False, 'message': 'Database connection failed'}

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM official_assets WHERE id=%s", (asset_id,))
            target = cursor.fetchone()
            if not target:
                return {'success': False, 'message': 'Asset not found'}

            asset_type = target['asset_type']

            if is_active:
                # Deactivate all of same type first
                cursor.execute("UPDATE official_assets SET is_active=0 WHERE asset_type=%s", (asset_type,))
                cursor.execute("UPDATE official_assets SET is_active=1 WHERE id=%s", (asset_id,))
            else:
                cursor.execute("UPDATE official_assets SET is_active=0 WHERE id=%s", (asset_id,))

        conn.commit()

        log_admin_action(
            admin_user_id,
            'ASSET_STATUS_CHANGE',
            {'asset_id': asset_id, 'asset_type': asset_type, 'new_status': is_active},
            req
        )

        return {'success': True, 'message': f"Asset status updated successfully.", 'is_active': is_active}
    except Exception as e:
        conn.rollback()
        return {'success': False, 'message': str(e)}
    finally:
        conn.close()

def delete_official_asset(asset_id, admin_user_id=None, req=None):
    """
    Deletes the asset record and deletes physical file from disk.
    """
    conn = get_db_connection()
    if not conn:
        return {'success': False, 'message': 'Database connection failed'}

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM official_assets WHERE id=%s", (asset_id,))
            asset = cursor.fetchone()
            if not asset:
                return {'success': False, 'message': 'Asset not found'}

            # Remove record
            cursor.execute("DELETE FROM official_assets WHERE id=%s", (asset_id,))
        conn.commit()

        # Remove physical file
        web_path = asset.get('file_path', '')
        filename = os.path.basename(web_path)
        full_path = os.path.join(ASSET_UPLOAD_DIR, filename)
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
            except Exception as e:
                print(f"Warning: could not delete file {full_path}: {e}")

        log_admin_action(
            admin_user_id,
            'ASSET_DELETE',
            {'asset_id': asset_id, 'asset_type': asset['asset_type'], 'filename': asset['original_file_name']},
            req
        )

        return {'success': True, 'message': f"{asset['asset_type'].replace('_', ' ').title()} deleted successfully."}
    except Exception as e:
        conn.rollback()
        return {'success': False, 'message': str(e)}
    finally:
        conn.close()
