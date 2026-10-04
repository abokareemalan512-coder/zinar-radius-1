# نسخة Render — ما تعمل شي (المزامنة تصير محلياً)
import logging
logger = logging.getLogger(__name__)

def sync_user(username, password): return True
def delete_user(username): return True
def pause_user(username): return True
def resume_user(username, password): return True
def user_exists(username): return False
