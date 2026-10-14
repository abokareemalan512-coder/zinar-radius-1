# ZINAR REAL RADIUS SYNC - يحترم كلمة سر كل زبون
import os
import logging
import psycopg2

logger = logging.getLogger(__name__)
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_conn():
    if not DATABASE_URL:
        return None
    return psycopg2.connect(DATABASE_URL)

def sync_user(username, password=None):
    """ياخد نفس كلمة السر يلي انت كتبتها بالموقع - اي شي بتحطو هو يلي رح يصير بالراديوس"""
    try:
        if not username or not password:
            logger.error(f"Missing username or password for {username}")
            return False
        
        pwd = str(password).strip()  # نفس كلمة السر يلي انت كتبتها، ارقام او حروف
        if not pwd:
            return False
        
        conn = get_conn()
        if not conn:
            return False
        cur = conn.cursor()
        cur.execute("DELETE FROM radcheck WHERE username=%s", (username,))
        cur.execute(
            "INSERT INTO radcheck (username, attribute, op, value) VALUES (%s, 'Cleartext-Password', ':=', %s)",
            (username, pwd)
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"✅ Synced {username} / {pwd}")
        return True
    except Exception as e:
        logger.error(f"sync_user error: {e}")
        return False

def delete_user(username):
    try:
        conn = get_conn()
        if not conn: return True
        cur = conn.cursor()
        cur.execute("DELETE FROM radcheck WHERE username=%s", (username,))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"delete error: {e}")
        return True

def pause_user(username):
    return delete_user(username)

def resume_user(username, password=None):
    return sync_user(username, password)

def user_exists(username):
    try:
        conn = get_conn()
        if not conn: return False
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM radcheck WHERE username=%s LIMIT 1", (username,))
        exists = cur.fetchone() is not None
        cur.close()
        conn.close()
        return exists
    except:
        return False
