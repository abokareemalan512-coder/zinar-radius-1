# radius_sync.py
import pymysql
import logging

logger = logging.getLogger(__name__)

DB = dict(host='localhost', user='radius', password='zinar512', database='radius', charset='utf8mb4')

def _conn():
    return pymysql.connect(**DB)

def _exec(sql, params=None, fetch=False):
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(sql, params or ())
        if fetch:
            r = cur.fetchall()
            c.close()
            return r
        c.commit()
        c.close()
        return True
    except Exception as e:
        logger.error(f"RADIUS-DB: {e}")
        return None if fetch else False

def sync_user(username, password):
    """إضافة/تحديث مستخدم في radcheck"""
    _exec("DELETE FROM radcheck WHERE username=%s", (username,))
    _exec("INSERT INTO radcheck (username, attribute, op, value) VALUES (%s,'Cleartext-Password',':=',%s)", (username, password))
    return True

def delete_user(username):
    """حذف مستخدم من radcheck"""
    _exec("DELETE FROM radcheck WHERE username=%s", (username,))
    return True

def pause_user(username):
    """إيقاف مؤقت — إضافة Auth-Type Reject"""
    _exec("DELETE FROM radcheck WHERE username=%s", (username,))
    _exec("INSERT INTO radcheck (username, attribute, op, value) VALUES (%s,'Auth-Type',':=','Reject')", (username,))
    return True

def resume_user(username, password):
    """تفعيل"""
    return sync_user(username, password)

def user_exists(username):
    r = _exec("SELECT id FROM radcheck WHERE username=%s AND attribute='Cleartext-Password'", (username,), fetch=True)
    return bool(r)
