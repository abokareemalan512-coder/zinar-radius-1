# نسخة Render - (الزامنة تصير محليا) - ZINAR REAL RADIUS SYNC
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
    """يضيف الزبون لجدول radcheck بكلمة سر zinar512 اذا ما انبعتت كلمة سر"""
    try:
        pwd = password if password else "zinar512"
        if not pwd or pwd.strip() == "":
            pwd = "zinar512"
        
        conn = get_conn()
        if not conn:
            logger.error("No DATABASE_URL")
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
        logger.info(f"✅ Synced radius user {username} with pwd {pwd}")
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
        logger.error(f"delete_user error: {e}")
        return True

def pause_user(username):
    # للايقاف نحذفو من radcheck
    return delete_user(username)

def resume_user(username, password="zinar512"):
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
