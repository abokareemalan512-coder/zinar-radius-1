# radius_sync.py
import os
import logging

logger = logging.getLogger(__name__)

# إذا على Render — تجاهل كل شي
ON_RENDER = os.environ.get('RENDER') == 'true' or os.environ.get('DATABASE_URL','').startswith('postgres')

if not ON_RENDER:
    import pymysql
    DB = dict(host='localhost', user='radius', password='zinar512',
              database='radius', charset='utf8mb4')

def _conn():
    return pymysql.connect(**DB)

def _exec(sql, params=None, fetch=False):
    if ON_RENDER: return True if not fetch else None
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(sql, params or ())
        if fetch:
            r = cur.fetchall(); c.close(); return r
        c.commit(); c.close(); return True
    except Exception as e:
        logger.error(f"RADIUS-DB: {e}")
        return None if fetch else False

def sync_user(username, password):
    if ON_RENDER: return True
    _exec("DELETE FROM radcheck WHERE username=%s", (username,))
    _exec("INSERT INTO radcheck (username,attribute,op,value) VALUES (%s,'Cleartext-Password',':=',%s)", (username, password))
    return True

def delete_user(username):
    if ON_RENDER: return True
    _exec("DELETE FROM radcheck WHERE username=%s", (username,))
    return True

def pause_user(username):
    if ON_RENDER: return True
    _exec("DELETE FROM radcheck WHERE username=%s", (username,))
    _exec("INSERT INTO radcheck (username,attribute,op,value) VALUES (%s,'Auth-Type',':=','Reject')", (username,))
    return True

def resume_user(username, password):
    return sync_user(username, password)

def user_exists(username):
    if ON_RENDER: return False
    r = _exec("SELECT id FROM radcheck WHERE username=%s AND attribute='Cleartext-Password'", (username,), fetch=True)
    return bool(r)
