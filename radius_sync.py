"""
radius_sync.py - نسخة "الموقع هو العقل"
لا تتصل بـ MikroTik مباشرة، بل تُنشئ أوامر في قاعدة البيانات
"""
import logging
logger = logging.getLogger(__name__)


def _queue(action, payload, router_name=None):
    """استيراد مؤجل لتفادي الاستيراد الدائري"""
    try:
        from app import queue_router_command
        return queue_router_command(action, payload, router_name)
    except Exception as e:
        logger.error(f"❌ radius_sync._queue: {e}")
        return None


def sync_user(username, password, package=None, user_type='hotspot'):
    """إضافة/تحديث مستخدم - يُنشئ أمراً في الطابور"""
    if not username or not password:
        return False
    _queue('sync_user', {
        'username': username,
        'password': password,
        'package': package or 'default',
        'user_type': user_type,
    })
    return True


def delete_user(username):
    if not username:
        return False
    _queue('delete_user', {'username': username})
    return True


def pause_user(username):
    if not username:
        return False
    _queue('pause_user', {'username': username})
    return True


def resume_user(username, password=None):
    if not username:
        return False
    _queue('resume_user', {'username': username, 'password': password})
    return True


def sync_all_users():
    """مزامنة كل المستخدمين"""
    try:
        from app import db, Subscriber, app as flask_app
        with flask_app.app_context():
            subs = Subscriber.query.all()
            payload = [{
                'username': s.username,
                'password': s.password,
                'package': s.package or 'default',
                'status': s.status or 'active',
                'user_type': s.user_type or 'hotspot',
            } for s in subs]
            _queue('sync_all', {'users': payload})
            logger.info(f"📤 أمر مزامنة شاملة لـ {len(subs)} مشترك")
            return len(subs)
    except Exception as e:
        logger.error(f"❌ sync_all_users: {e}")
        return 0
