import os
import logging
import psycopg2

logger = logging.getLogger(__name__)

def get_conn():
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        return None
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    if '+psycopg' in database_url:
        database_url = database_url.replace('+psycopg', '')
    try:
        return psycopg2.connect(database_url)
    except Exception as e:
        logger.error(f"DB Connection Error: {e}")
        return None

def sync_user(username, password=None, package=None, user_type='hotspot'):
    try:
        if not username or not password:
            return False
        conn = get_conn()
        if not conn: return False
        cur = conn.cursor()
        cur.execute("DELETE FROM radcheck WHERE username=%s", (username,))
        cur.execute("DELETE FROM radreply WHERE username=%s", (username,))
        cur.execute("INSERT INTO radcheck (username, attribute, op, value) VALUES (%s, 'Cleartext-Password', ':=', %s)", (username, str(password).strip()))
        if package:
            cur.execute("INSERT INTO radreply (username, attribute, op, value) VALUES (%s, 'Mikrotik-Group', ':=', %s)", (username, package))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"sync_user error: {e}")
        return False

def delete_user(username):
    try:
        conn = get_conn()
        if not conn: return False
        cur = conn.cursor()
        cur.execute("DELETE FROM radcheck WHERE username=%s", (username,))
        cur.execute("DELETE FROM radreply WHERE username=%s", (username,))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception:
        return False

def pause_user(username):
    return delete_user(username)

def resume_user(username, password=None):
    return sync_user(username, password)

def sync_all_users():
    pass
