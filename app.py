import os
import re
import io
import csv
import random
import string
import logging
import traceback
import calendar
import socket
import time
import threading
import ipaddress
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, session, send_file
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import paramiko

try:
    import requests
except ImportError:
    requests = None

try:
    import radius_sync
except ImportError:
    radius_sync = None

try:
    from librouteros import connect
    from librouteros.query import Key
    LIBROUTEROS_AVAILABLE = True
except ImportError:
    LIBROUTEROS_AVAILABLE = False

# ============ الإعدادات ============

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'zinar-secret-key-2024')
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not LIBROUTEROS_AVAILABLE:
    logger.warning("⚠️ مكتبة librouteros غير مثبتة - مراقبة الترافيك معطلة")

LOCAL_TZ = ZoneInfo("Asia/Damascus")
IMPORT_API_KEY = os.environ.get('IMPORT_API_KEY', 'zinar-import-key-2026')

_traffic_cache = {}

# ============ Database Config ============

database_url = os.environ.get('DATABASE_URL')
if not database_url:
    database_url = 'sqlite:///zinar.db'
else:
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    if 'postgresql://' in database_url and '+psycopg' not in database_url:
        database_url = database_url.replace('postgresql://', 'postgresql+psycopg://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 180,
    'pool_size': 5,
    'max_overflow': 10,
    'pool_timeout': 30,
    'connect_args': {"sslmode": "require"} if 'postgresql' in database_url else {}
}

_masked = database_url.split('@')[-1] if '@' in database_url else database_url
logger.info(f"📊 DB: ...@{_masked}")

db = SQLAlchemy(app)


@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()


@app.template_filter('localtime')
def localtime_filter(dt, format='%Y-%m-%d %H:%M:%S'):
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(LOCAL_TZ).strftime(format)


try:
    from api_sync import sync_bp
    app.register_blueprint(sync_bp)
except ImportError:
    logger.warning("⚠️ Blueprint api_sync غير موجود، تم التجاوز.")


# ============ Models ============

class Router(db.Model):
    __tablename__ = 'routers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    ip_address = db.Column(db.String(50), nullable=False)
    username = db.Column(db.String(50), nullable=False)
    password = db.Column(db.String(150), nullable=False)
    port = db.Column(db.Integer, default=22)
    api_port = db.Column(db.Integer, default=13)
    is_master = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AdminUser(db.Model):
    __tablename__ = 'admin_users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Subscriber(db.Model):
    __tablename__ = 'subscribers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    username = db.Column(db.String(100), nullable=False)
    password = db.Column(db.String(150), nullable=False)
    package = db.Column(db.String(100))
    user_type = db.Column(db.String(20), default='pppoe')
    router_id = db.Column(db.Integer)
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    first_used_at = db.Column(db.DateTime)
    current_ip = db.Column(db.String(50))
    ip_updated_at = db.Column(db.DateTime)
    last_seen_at = db.Column(db.DateTime)
    session_uptime = db.Column(db.String(50))
    session_rx_bytes = db.Column(db.BigInteger, default=0)
    session_tx_bytes = db.Column(db.BigInteger, default=0)
    connected_at = db.Column(db.DateTime)


class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    subscriber_id = db.Column(db.Integer, db.ForeignKey('subscribers.id'))
    amount = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Package(db.Model):
    __tablename__ = 'packages'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    speed = db.Column(db.String(50))
    price = db.Column(db.Float, default=0)
    duration = db.Column(db.Integer, default=30)
    duration_unit = db.Column(db.String(10), default='days')
    user_type = db.Column(db.String(20), default='pppoe')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SystemEvent(db.Model):
    __tablename__ = 'system_events'
    id = db.Column(db.Integer, primary_key=True)
    admin_name = db.Column(db.String(50))
    action = db.Column(db.String(100))
    target = db.Column(db.String(100))
    details = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TelegramSetting(db.Model):
    __tablename__ = 'telegram_settings'
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(255))
    chat_id = db.Column(db.String(100))
    enabled = db.Column(db.Boolean, default=False)
    notify_new_subscriber = db.Column(db.Boolean, default=True)
    notify_subscriber_expired = db.Column(db.Boolean, default=True)
    notify_bulk_add = db.Column(db.Boolean, default=True)
    notify_admin_action = db.Column(db.Boolean, default=False)
    notify_router_status = db.Column(db.Boolean, default=True)


class TelegramLog(db.Model):
    __tablename__ = 'telegram_logs'
    id = db.Column(db.Integer, primary_key=True)
    message_type = db.Column(db.String(50))
    status = db.Column(db.String(20))
    message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============ Helpers ============

def get_local_time():
    return datetime.now(LOCAL_TZ)


def get_local_time_str():
    return get_local_time().strftime('%Y-%m-%d %H:%M:%S')


def log_event(action, target="", details="", admin_name=None):
    try:
        if not admin_name:
            admin_name = session.get('admin_name', 'النظام')
        evt = SystemEvent(admin_name=admin_name, action=action, target=target, details=details)
        db.session.add(evt)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f"⚠️ فشل تسجيل الحدث: {e}")


def add_months(source_date, months):
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(source_date.day, last_day)
    return source_date.replace(year=year, month=month, day=day)


def calculate_expiry(pkg, start_date=None):
    if start_date is None:
        start_date = datetime.utcnow()
    if not pkg or not pkg.duration:
        return None
    if pkg.duration_unit == 'months':
        return add_months(start_date, pkg.duration)
    return start_date + timedelta(days=pkg.duration)


def package_to_profile(name):
    if not name:
        return 'default'
    return name.strip().replace(' ', '_')


def _day_bounds(day=None):
    if day is None:
        day = datetime.utcnow()
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _safe_str(value, default=''):
    if value is None:
        return default
    if isinstance(value, bytes):
        try:
            return value.decode('utf-8', errors='ignore')
        except Exception:
            return str(value)
    return str(value)


def _safe_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, bytes):
        try:
            value = value.decode('utf-8', errors='ignore')
        except Exception:
            return default
    s = str(value).lower()
    return s in ('true', 'yes', '1')


def _safe_int(value, default=0):
    try:
        return int(_safe_str(value, str(default)))
    except (ValueError, TypeError):
        return default


def _calculate_connected_at(uptime_str):
    """تحويل uptime مثل '1h30m25s' إلى datetime"""
    try:
        if not uptime_str:
            return None
        total_seconds = 0
        m = re.search(r'(\d+)w', uptime_str)
        if m: total_seconds += int(m.group(1)) * 604800
        m = re.search(r'(\d+)d', uptime_str)
        if m: total_seconds += int(m.group(1)) * 86400
        m = re.search(r'(\d+)h', uptime_str)
        if m: total_seconds += int(m.group(1)) * 3600
        m = re.search(r'(\d+)m', uptime_str)
        if m: total_seconds += int(m.group(1)) * 60
        m = re.search(r'(\d+)s', uptime_str)
        if m: total_seconds += int(m.group(1))
        return datetime.utcnow() - timedelta(seconds=total_seconds)
    except Exception:
        return None


# ============ MikroTik Escape Decoder ============

def decode_mikrotik_escapes(text):
    if not text or '\\' not in text:
        return text
    result = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == '\\' and i + 2 < n and all(c in '0123456789ABCDEFabcdef' for c in text[i+1:i+3]):
            byte_seq = []
            while i + 2 < n and text[i] == '\\' and all(c in '0123456789ABCDEFabcdef' for c in text[i+1:i+3]):
                byte_seq.append(int(text[i+1:i+3], 16))
                i += 3
            try:
                decoded = bytes(byte_seq).decode('utf-8')
                result.append(decoded)
            except UnicodeDecodeError:
                try:
                    decoded = bytes(byte_seq).decode('windows-1256')
                    result.append(decoded)
                except UnicodeDecodeError:
                    result.append(''.join(f'\\{b:02X}' for b in byte_seq))
        else:
            result.append(text[i])
            i += 1
    return ''.join(result)


# ============ MikroTik Parser ============

def _extract_kv(text, params):
    for stop in [' on-up=', ' on-down=', 'on-up=', 'on-down=']:
        idx = text.find(stop)
        if idx != -1:
            text = text[:idx]
            break
    pattern = r'([\w\-]+)\s*=\s*(?:"([^"]*)"|(\S+))'
    for match in re.finditer(pattern, text):
        key = match.group(1).lower()
        value = match.group(2) if match.group(2) is not None else match.group(3)
        if key not in params:
            params[key] = decode_mikrotik_escapes(value)


def _parse_print_format(lines, debug_info, packages, subscribers):
    current_section = None
    current_entry = None
    current_disabled = False

    def finalize():
        nonlocal current_entry, current_disabled
        if current_entry is None:
            return
        name = current_entry.get('name', '').strip()
        if not name:
            current_entry = None
            current_disabled = False
            return
        if current_section == 'profile':
            if name not in ('default', 'default-encryption'):
                rate_limit = current_entry.get('rate-limit', '').strip()
                packages.append({
                    'name': name, 'speed': rate_limit if rate_limit else 'N/A',
                    'price': 0, 'duration': 30, 'duration_unit': 'days', 'user_type': 'pppoe'
                })
                debug_info['profile_lines'] += 1
        elif current_section == 'secret':
            password = current_entry.get('password', '').strip()
            profile = current_entry.get('profile', '').strip()
            comment = current_entry.get('comment', '').strip()
            service = current_entry.get('service', 'pppoe').strip().lower()
            status = 'paused' if current_disabled else 'active'
            user_type = 'hotspot' if 'hotspot' in service else 'pppoe'
            subscribers.append({
                'username': name, 'password': password, 'package': profile,
                'name': comment if comment else name, 'user_type': user_type, 'status': status
            })
            debug_info['secret_lines'] += 1
        current_entry = None
        current_disabled = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.startswith('/'):
            finalize()
            lower = stripped.lower()
            if 'ppp/profile' in lower or 'ppp profile' in lower:
                current_section = 'profile'
                debug_info['sections_found'].append('profile')
            elif 'ppp/secret' in lower or 'ppp secret' in lower:
                current_section = 'secret'
                debug_info['sections_found'].append('secret')
            else:
                current_section = None
            continue
        if stripped.startswith('Flags:'):
            continue
        if not current_section:
            continue
        m = re.match(r'^\s*(\d+)\s+(.*)$', line)
        if m:
            finalize()
            content = m.group(2)
            current_disabled = content.startswith('X ')
            content = re.sub(r'^[X\*]\s+', '', content).strip()
            current_entry = {}
            _extract_kv(content, current_entry)
        else:
            if current_entry is not None:
                _extract_kv(stripped, current_entry)
    finalize()


def _parse_export_format(lines, debug_info, packages, subscribers):
    current_section = None
    merged = []
    buffer = ''
    for line in lines:
        if line.rstrip().endswith('\\'):
            buffer += line.rstrip()[:-1] + ' '
        else:
            if buffer:
                merged.append(buffer + line)
                buffer = ''
            else:
                merged.append(line)
    if buffer:
        merged.append(buffer)
    for line in merged:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.startswith('/'):
            lower = stripped.lower()
            if 'ppp/profile' in lower or 'ppp profile' in lower:
                current_section = 'profile'
                debug_info['sections_found'].append('profile')
            elif 'ppp/secret' in lower or 'ppp secret' in lower:
                current_section = 'secret'
                debug_info['sections_found'].append('secret')
            else:
                current_section = None
            continue
        if not current_section:
            continue
        if stripped.startswith('add ') or stripped.startswith('set '):
            params = {}
            _extract_kv(stripped, params)
            name = params.get('name', '').strip()
            if not name:
                continue
            if current_section == 'profile':
                if name not in ('default', 'default-encryption'):
                    rate_limit = params.get('rate-limit', '').strip()
                    packages.append({
                        'name': name, 'speed': rate_limit if rate_limit else 'N/A',
                        'price': 0, 'duration': 30, 'duration_unit': 'days', 'user_type': 'pppoe'
                    })
                    debug_info['profile_lines'] += 1
            elif current_section == 'secret':
                password = params.get('password', '').strip()
                profile = params.get('profile', '').strip()
                comment = params.get('comment', '').strip()
                disabled = params.get('disabled', 'no').strip().lower()
                service = params.get('service', 'pppoe').strip().lower()
                status = 'paused' if disabled in ('yes', 'true', '1') else 'active'
                user_type = 'hotspot' if 'hotspot' in service else 'pppoe'
                subscribers.append({
                    'username': name, 'password': password, 'package': profile,
                    'name': comment if comment else name, 'user_type': user_type, 'status': status
                })
                debug_info['secret_lines'] += 1


def parse_mikrotik_rsc(content):
    packages = []
    subscribers = []
    debug_info = {
        'lines_read': 0, 'sections_found': [], 'profile_lines': 0,
        'secret_lines': 0, 'preview': '', 'format': 'unknown',
    }
    if content.startswith('\ufeff'):
        content = content[1:]
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    lines = content.split('\n')
    debug_info['lines_read'] = len(lines)
    debug_info['preview'] = '\n'.join(lines[:20])
    is_print = False
    for line in lines[:80]:
        s = line.strip()
        if s.startswith('Flags:'):
            is_print = True
            break
        if s.startswith('/') and s.endswith(' print'):
            is_print = True
            break
    debug_info['format'] = 'print' if is_print else 'export'
    if is_print:
        _parse_print_format(lines, debug_info, packages, subscribers)
    else:
        _parse_export_format(lines, debug_info, packages, subscribers)
    return packages, subscribers, debug_info


# ============ Telegram Helper ============

def get_telegram_settings():
    try:
        return TelegramSetting.query.first()
    except Exception:
        return None


def log_telegram(message, message_type='info', status='success'):
    try:
        log = TelegramLog(message_type=message_type, status=status, message=message[:2000])
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning(f"⚠️ فشل تسجيل log تليجرام: {e}")


def send_telegram_message(message, message_type='info', force=False):
    if not requests:
        return False, 'requests library not installed'
    settings = get_telegram_settings()
    if not settings:
        return False, 'No Telegram settings found'
    if not force and (not settings.enabled or not settings.token or not settings.chat_id):
        return False, 'Telegram disabled or incomplete settings'
    token = settings.token.strip() if settings.token else ''
    chat_id = str(settings.chat_id).strip() if settings.chat_id else ''
    if not token or not chat_id:
        return False, 'Missing telegram token or chat id'
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        if result.get("ok"):
            log_telegram(message, message_type=message_type, status='success')
            return True, 'Sent successfully'
        else:
            log_telegram(message, message_type=message_type, status='failed')
            return False, result.get("description", "Unknown Telegram error")
    except Exception as e:
        log_telegram(str(e), message_type=message_type, status='failed')
        return False, str(e)


@app.route('/api/telegram/webhook', methods=['POST'])
def telegram_webhook():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'ok': True})
        msg = data.get('message') or data.get('channel_post')
        if msg:
            chat_id = msg.get('chat', {}).get('id')
            text = msg.get('text', '')
            chat_title = msg.get('chat', {}).get('title', '')
            user_info = msg.get('from', {})
            if user_info.get('is_bot', False):
                return jsonify({'ok': True})
            user_name = user_info.get('username') or user_info.get('first_name', 'مستخدم')
            log = TelegramLog(
                message_type='incoming_group' if chat_title else 'incoming',
                status='success',
                message=f"📥 {chat_title} | {user_name}:\n{text}" if chat_title else f"📥 {user_name}:\n{text}"
            )
            db.session.add(log)
            db.session.commit()
            if text.strip() == '/start' and not chat_title:
                send_telegram_message(
                    f"أهلاً بك يا {user_name} 👋\nتم استلام رسالتك وربط حسابك بنجاح مع النظام.",
                    message_type='reply', force=True
                )
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False}), 500


def notify_new_subscriber(username):
    settings = get_telegram_settings()
    if not settings or not settings.enabled or not settings.notify_new_subscriber:
        return False
    if not settings.token or not settings.chat_id:
        return False
    msg = f"*🆕 مشترك جديد*\n👤 المستخدم: `{username}`\n🕒 الوقت: {get_local_time_str()}"
    return send_telegram_message(msg, message_type='new_subscriber')[0]


def notify_expired_subscriber(username):
    settings = get_telegram_settings()
    if not settings or not settings.enabled or not settings.notify_subscriber_expired:
        return False
    if not settings.token or not settings.chat_id:
        return False
    msg = f"*⏰ اشتراك منتهي*\n👤 المستخدم: `{username}`\n⚠️ تم إنهاء الاشتراك"
    return send_telegram_message(msg, message_type='expired_subscriber')[0]


def notify_bulk_add(created, failed, package_name):
    settings = get_telegram_settings()
    if not settings or not settings.enabled or not settings.notify_bulk_add:
        return False
    if not settings.token or not settings.chat_id:
        return False
    msg = f"*📦 إضافة جماعية*\n📦 الباقة: `{package_name or 'غير محددة'}`\n✅ تم إنشاء: `{created}`\n❌ فشل: `{failed}`"
    return send_telegram_message(msg, message_type='bulk_add')[0]


def notify_admin_action(action_text):
    settings = get_telegram_settings()
    if not settings or not settings.enabled or not settings.notify_admin_action:
        return False
    if not settings.token or not settings.chat_id:
        return False
    msg = f"*⚙️ إجراء إداري*\n{action_text}"
    return send_telegram_message(msg, message_type='admin_action')[0]


def notify_router_status_change(router_name, ip_address, is_up):
    settings = get_telegram_settings()
    if not settings or not settings.enabled or not settings.notify_router_status:
        return False
    if not settings.token or not settings.chat_id:
        return False
    status_symbol = "🟢" if is_up else "🔴"
    status_text = "يعمل" if is_up else "متوقف"
    msg = f"{status_symbol} {router_name} `{ip_address}` {status_text}"
    return send_telegram_message(msg, message_type='router_status')[0]


# ============ Background Router Monitor ============

def is_private_ip(ip):
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


def check_router_connection(ip, port=22, timeout=3):
    if is_private_ip(ip):
        return 'private'
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, int(port)))
        return True
    except Exception:
        return False
    finally:
        if s:
            s.close()


def background_router_monitor():
    time.sleep(15)
    while True:
        try:
            with app.app_context():
                routers = Router.query.all()
                for r in routers:
                    try:
                        current_state = check_router_connection(r.ip_address, r.port or 22)
                        if current_state == 'private':
                            if not r.is_active:
                                r.is_active = True
                                db.session.commit()
                            continue
                        if r.is_active != current_state:
                            r.is_active = current_state
                            db.session.commit()
                            notify_router_status_change(r.name, r.ip_address, current_state)
                    except Exception as db_err:
                        db.session.rollback()
                        logger.warning(f"⚠️ خطأ: {db_err}")
        except Exception as e:
            logger.warning(f"⚠️ خطأ في مراقبة الراوترات: {e}")
        finally:
            try:
                db.session.remove()
            except Exception:
                pass
        time.sleep(60)


# ============ MikroTik API Helper ============

def get_mikrotik_api(router):
    if not LIBROUTEROS_AVAILABLE:
        raise Exception("مكتبة librouteros غير مثبتة")
    try:
        api_port = router.api_port or 13
        logger.info(f"🔌 اتصال API: {router.ip_address}:{api_port} (user={router.username})")
        api = connect(
            username=router.username, password=router.password,
            host=router.ip_address, port=api_port, timeout=5
        )
        return api
    except Exception as e:
        raise Exception(f"فشل الاتصال بالـ API على المنفذ {router.api_port}: {str(e)}")


# ============ Background IP + Session Updater ============

def fetch_active_ips_from_router(router):
    """
    جلب المستخدمين النشطين مع حجم البيانات الحقيقي (تحميل/رفع)
    يتم قراءة البيانات من الواجهات الديناميكية <pppoe-username>
    """
    if not LIBROUTEROS_AVAILABLE:
        return {}
    result = {}
    api = None
    try:
        api = get_mikrotik_api(router)
        
        # ✅ الخطوة 1: جلب كل الواجهات وبناء خريطة (name → stats)
        interfaces_map = {}
        try:
            for iface in api.path('interface'):
                name = _safe_str(iface.get('name'))
                if not name:
                    continue
                interfaces_map[name] = {
                    'rx_byte': _safe_int(iface.get('rx-byte', 0), 0),
                    'tx_byte': _safe_int(iface.get('tx-byte', 0), 0),
                }
            logger.info(f"📊 {router.name}: تم قراءة {len(interfaces_map)} واجهة")
        except Exception as e:
            logger.warning(f"⚠️ فشل جلب الواجهات من {router.name}: {e}")
        
        # ✅ الخطوة 2: جلب جلسات PPPoE النشطة
        try:
            for ppp in api.path('ppp', 'active'):
                uname = _safe_str(ppp.get('name'))
                addr = _safe_str(ppp.get('address'))
                if not uname or not addr or addr == '0.0.0.0':
                    continue
                
                # ✅ اسم الواجهة الديناميكية في MikroTik
                iface_name = f"<pppoe-{uname}>"
                iface_stats = interfaces_map.get(iface_name, {})
                rx_bytes = iface_stats.get('rx_byte', 0)
                tx_bytes = iface_stats.get('tx_byte', 0)
                
                # إذا لم نجد الواجهة، جرّب البحث الجزئي
                if not iface_stats:
                    for k, v in interfaces_map.items():
                        if uname in k and 'pppoe' in k.lower():
                            rx_bytes = v.get('rx_byte', 0)
                            tx_bytes = v.get('tx_byte', 0)
                            break
                
                result[uname] = {
                    'ip': addr,
                    'uptime': _safe_str(ppp.get('uptime', '')),
                    'rx_bytes': rx_bytes,
                    'tx_bytes': tx_bytes,
                    'type': 'pppoe',
                    'router_id': router.id
                }
        except Exception as e:
            logger.warning(f"⚠️ فشل جلب PPP active من {router.name}: {e}")
        
        # ✅ الخطوة 3: جلب جلسات Hotspot النشطة
        try:
            for hs in api.path('ip', 'hotspot', 'active'):
                uname = _safe_str(hs.get('user'))
                addr = _safe_str(hs.get('address'))
                if not uname or not addr:
                    continue
                if ':' in addr:
                    addr = addr.split(':')[0]
                rx_bytes = _safe_int(hs.get('bytes-in', 0), 0)
                tx_bytes = _safe_int(hs.get('bytes-out', 0), 0)
                result[uname] = {
                    'ip': addr,
                    'uptime': _safe_str(hs.get('uptime', '')),
                    'rx_bytes': rx_bytes,
                    'tx_bytes': tx_bytes,
                    'type': 'hotspot',
                    'router_id': router.id
                }
        except Exception as e:
            logger.warning(f"⚠️ فشل جلب Hotspot active من {router.name}: {e}")
        
        logger.info(f"✅ {router.name}: تم جلب {len(result)} مشترك نشط")
        return result
    except Exception as e:
        logger.warning(f"⚠️ فشل جلب IPs من {router.name}: {e}")
        return {}
    finally:
        if api:
            try:
                api.close()
            except Exception:
                pass


def background_ip_updater():
    time.sleep(30)
    while True:
        try:
            with app.app_context():
                routers = Router.query.all()
                total_updated = 0
                for router in routers:
                    try:
                        active_ips = fetch_active_ips_from_router(router)
                        if not active_ips:
                            continue
                        for username, info in active_ips.items():
                            sub = Subscriber.query.filter_by(username=username).first()
                            if sub:
                                changed = False
                                if sub.current_ip != info['ip']:
                                    sub.current_ip = info['ip']
                                    changed = True
                                if sub.router_id != router.id:
                                    sub.router_id = router.id
                                    changed = True
                                sub.session_uptime = info.get('uptime', '')
                                sub.session_rx_bytes = info.get('rx_bytes', 0)
                                sub.session_tx_bytes = info.get('tx_bytes', 0)
                                if info.get('uptime'):
                                    sub.connected_at = _calculate_connected_at(info['uptime'])
                                sub.ip_updated_at = datetime.utcnow()
                                sub.last_seen_at = datetime.utcnow()
                                if changed:
                                    total_updated += 1
                        db.session.commit()
                    except Exception as e:
                        db.session.rollback()
                        logger.warning(f"⚠️ خطأ تحديث IP من {router.name}: {e}")
                if total_updated > 0:
                    logger.info(f"✅ تم تحديث IP لـ {total_updated} مشترك")
        except Exception as e:
            logger.warning(f"⚠️ خطأ في background_ip_updater: {e}")
        finally:
            try:
                db.session.remove()
            except Exception:
                pass
        time.sleep(120)


# ============ Kick via SSH ============

def kick_user_via_ssh(router, username, user_type='pppoe'):
    if not router:
        return False, "no router"
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=router.ip_address, port=router.port or 22,
            username=router.username, password=router.password,
            timeout=8, allow_agent=False, look_for_keys=False,
        )
        if user_type == 'hotspot':
            cmd = f'/ip hotspot active remove [find user="{username}"]'
        else:
            cmd = f'/ppp active remove [find name="{username}"]'
        stdin, stdout, stderr = ssh.exec_command(cmd)
        stdout.read()
        ssh.close()
        logger.info(f"👢 KICK: {username} on {router.name}")
        return True, "kicked"
    except Exception as e:
        logger.warning(f"⚠️ KICK فشل {username}: {e}")
        return False, str(e)


def kick_subscriber(sub):
    if os.environ.get("RENDER") == "true":
        return
    if not sub:
        return
    if sub.router_id:
        r = Router.query.get(sub.router_id)
        if r:
            kick_user_via_ssh(r, sub.username, sub.user_type or 'pppoe')
    other_routers = Router.query.filter(
        Router.is_active == True, Router.id != (sub.router_id or 0)
    ).all()
    for r in other_routers:
        try:
            kick_user_via_ssh(r, sub.username, sub.user_type or 'pppoe')
        except Exception:
            pass


# ============ Init DB ============

def init_database():
    with app.app_context():
        try:
            db.create_all()
            if not AdminUser.query.filter_by(username='admin').first():
                db.session.add(AdminUser(
                    username='admin',
                    password=generate_password_hash('admin123'),
                    email='admin@zinar.com'
                ))
                db.session.commit()
            if not TelegramSetting.query.first():
                db.session.add(TelegramSetting(
                    enabled=False, notify_new_subscriber=True, notify_subscriber_expired=True,
                    notify_bulk_add=True, notify_admin_action=False, notify_router_status=True
                ))
                db.session.commit()
            logger.info("✅ تم تهيئة قاعدة البيانات")
        except Exception as e:
            db.session.rollback()
            if "already exists" not in str(e).lower():
                logger.error(f"❌ خطأ تهيئة قاعدة البيانات: {e}")


def ensure_columns():
    with app.app_context():
        try:
            from sqlalchemy import text, inspect
            insp = inspect(db.engine)
            tables = insp.get_table_names()
            with db.engine.connect() as conn:
                if 'routers' in tables:
                    cols = [c['name'] for c in insp.get_columns('routers')]
                    if 'is_active' not in cols:
                        conn.execute(text("ALTER TABLE routers ADD COLUMN is_active BOOLEAN DEFAULT TRUE"))
                    if 'api_port' not in cols:
                        conn.execute(text("ALTER TABLE routers ADD COLUMN api_port INTEGER DEFAULT 13"))
                if 'telegram_settings' in tables:
                    cols = [c['name'] for c in insp.get_columns('telegram_settings')]
                    if 'notify_router_status' not in cols:
                        conn.execute(text("ALTER TABLE telegram_settings ADD COLUMN notify_router_status BOOLEAN DEFAULT TRUE"))
                if 'subscribers' in tables:
                    cols = [c['name'] for c in insp.get_columns('subscribers')]
                    for col, sql in [
                        ('name', "ALTER TABLE subscribers ADD COLUMN name VARCHAR(100)"),
                        ('user_type', "ALTER TABLE subscribers ADD COLUMN user_type VARCHAR(20) DEFAULT 'pppoe'"),
                        ('first_used_at', "ALTER TABLE subscribers ADD COLUMN first_used_at TIMESTAMP"),
                        ('current_ip', "ALTER TABLE subscribers ADD COLUMN current_ip VARCHAR(50)"),
                        ('ip_updated_at', "ALTER TABLE subscribers ADD COLUMN ip_updated_at TIMESTAMP"),
                        ('last_seen_at', "ALTER TABLE subscribers ADD COLUMN last_seen_at TIMESTAMP"),
                        ('session_uptime', "ALTER TABLE subscribers ADD COLUMN session_uptime VARCHAR(50)"),
                        ('session_rx_bytes', "ALTER TABLE subscribers ADD COLUMN session_rx_bytes BIGINT DEFAULT 0"),
                        ('session_tx_bytes', "ALTER TABLE subscribers ADD COLUMN session_tx_bytes BIGINT DEFAULT 0"),
                        ('connected_at', "ALTER TABLE subscribers ADD COLUMN connected_at TIMESTAMP"),
                    ]:
                        if col not in cols:
                            conn.execute(text(sql))
                if 'packages' in tables:
                    cols = [c['name'] for c in insp.get_columns('packages')]
                    for col, sql in [
                        ('duration_unit', "ALTER TABLE packages ADD COLUMN duration_unit VARCHAR(10) DEFAULT 'days'"),
                        ('user_type', "ALTER TABLE packages ADD COLUMN user_type VARCHAR(20) DEFAULT 'pppoe'"),
                    ]:
                        if col not in cols:
                            conn.execute(text(sql))
                conn.commit()
            logger.info("✅ فحص الأعمدة اكتمل")
        except Exception as e:
            logger.warning(f"⚠️ ensure_columns: {e}")


init_database()
ensure_columns()

monitor_thread = threading.Thread(target=background_router_monitor, daemon=True)
monitor_thread.start()

ip_updater_thread = threading.Thread(target=background_ip_updater, daemon=True)
ip_updater_thread.start()


# ============ API للميكروتيك ============

@app.route('/api/auth', methods=['GET', 'POST'])
def api_auth():
    if request.method == 'POST':
        data = request.form if request.form else (request.get_json(silent=True) or {})
        username = (data.get('user') or data.get('username') or '').strip()
        password = (data.get('pass') or data.get('password') or '').strip()
    else:
        username = request.args.get('user', '').strip()
        password = request.args.get('pass', '').strip()
    client_ip = request.remote_addr
    logger.info(f"🔐 AUTH [{client_ip}]: user={username}")
    if not username:
        return jsonify({'result': 'deny', 'reason': 'no_username'})
    sub = Subscriber.query.filter_by(username=username).first()
    if not sub:
        return jsonify({'result': 'deny', 'reason': 'user_not_found'})
    if password and sub.password != password:
        return jsonify({'result': 'deny', 'reason': 'wrong_password'})
    if sub.status == 'paused':
        return jsonify({'result': 'deny', 'reason': 'suspended'})
    if sub.status == 'expired':
        return jsonify({'result': 'deny', 'reason': 'expired'})
    now = datetime.utcnow()
    if sub.expires_at and sub.expires_at < now:
        sub.status = 'expired'
        db.session.commit()
        try:
            notify_expired_subscriber(sub.username)
        except Exception:
            pass
        return jsonify({'result': 'deny', 'reason': 'expired'})
    if not sub.expires_at:
        pkg = Package.query.filter_by(name=sub.package).first() if sub.package else None
        if pkg and pkg.duration:
            sub.first_used_at = now
            sub.expires_at = calculate_expiry(pkg, now)
            db.session.commit()
    profile = package_to_profile(sub.package) if sub.package else 'default'
    expires_str = sub.expires_at.strftime('%Y-%m-%d %H:%M:%S') if sub.expires_at else ''
    return jsonify({
        'result': 'allow', 'profile': profile, 'expires': expires_str,
        'user_type': sub.user_type or 'pppoe', 'name': sub.name or sub.username
    })


@app.route('/api/log', methods=['POST'])
def api_log():
    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    logger.info(f"📡 Mikrotik: {data}")
    return jsonify({'ok': True})


@app.route('/api/router_notify', methods=['POST', 'GET'])
def api_router_notify():
    try:
        data = {}
        if request.is_json:
            data = request.get_json()
        elif request.form:
            data = request.form.to_dict()
        elif request.args:
            data = request.args.to_dict()
        router_name = data.get('name', 'راوتر غير معروف')
        status = data.get('status', 'unknown').lower()
        ip_address = data.get('ip', '')
        if status in ('working', 'up', 'online'):
            status_ar, status_icon = 'يعمل', '🟢'
        elif status in ('stopped', 'down', 'offline'):
            status_ar, status_icon = 'متوقف', '🔴'
        else:
            status_ar, status_icon = 'غير معروف', '⚪'
        message = f"{status_icon} الراوتر {router_name} ({ip_address}) {status_ar}"
        log = TelegramLog(message_type='router_alert', status='success', message=message)
        db.session.add(log)
        log_event('تنبيه راوتر', router_name, message, admin_name='الميكروتيك')
        db.session.commit()
        try:
            send_telegram_message(message, message_type='router_alert')
        except Exception as tg_err:
            logger.warning(f"Telegram send failed: {tg_err}")
        return jsonify({'ok': True, 'message': 'Notification received', 'data': data})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/import_subscribers', methods=['POST'])
def api_import_subscribers():
    try:
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if api_key != IMPORT_API_KEY:
            return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
        data = request.get_json()
        if not data or not isinstance(data, list):
            return jsonify({'ok': False, 'error': 'Invalid data format.'}), 400
        imported = updated = skipped = 0
        for item in data:
            username = str(item.get('username', '')).strip()
            password = str(item.get('password', '')).strip()
            package = str(item.get('package', '')).strip()
            user_type = str(item.get('user_type', 'pppoe')).strip()
            status = str(item.get('status', 'active')).strip()
            name = str(item.get('name', username)).strip()
            if not username or not password:
                skipped += 1
                continue
            if user_type not in ('pppoe', 'hotspot'):
                user_type = 'pppoe'
            if status not in ('active', 'paused', 'expired'):
                status = 'active'
            sub = Subscriber.query.filter_by(username=username).first()
            if sub:
                sub.password = password
                sub.package = package
                sub.user_type = user_type
                sub.status = status
                sub.name = name
                updated += 1
            else:
                db.session.add(Subscriber(
                    name=name, username=username, password=password,
                    package=package, user_type=user_type, status=status, expires_at=None
                ))
                imported += 1
        db.session.commit()
        log_event('استيراد مشتركين (API)', f'{imported + updated} مشترك',
                  f'جديد: {imported} | محدّث: {updated} | متجاهل: {skipped}', admin_name='النظام (API)')
        return jsonify({
            'ok': True, 'imported': imported, 'updated': updated, 'skipped': skipped,
            'total': len(data),
            'message': f'تم بنجاح: {imported} مشترك جديد، {updated} محدّث، {skipped} متجاهل.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/import_packages', methods=['POST'])
def api_import_packages():
    try:
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if api_key != IMPORT_API_KEY:
            return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
        data = request.get_json()
        if not data or not isinstance(data, list):
            return jsonify({'ok': False, 'error': 'Invalid data format.'}), 400
        imported = updated = skipped = 0
        for item in data:
            name = str(item.get('name', '')).strip()
            speed = str(item.get('speed', '')).strip()
            price = item.get('price', 0)
            duration = item.get('duration', 30)
            duration_unit = str(item.get('duration_unit', 'days')).strip()
            user_type = str(item.get('user_type', 'pppoe')).strip()
            if not name:
                skipped += 1
                continue
            try:
                price = float(price) if price else 0
            except (ValueError, TypeError):
                price = 0
            try:
                duration = int(duration) if duration else 30
            except (ValueError, TypeError):
                duration = 30
            if duration_unit not in ('days', 'months'):
                duration_unit = 'days'
            if user_type not in ('pppoe', 'hotspot'):
                user_type = 'pppoe'
            pkg = Package.query.filter_by(name=name).first()
            if pkg:
                pkg.speed = speed or pkg.speed
                pkg.price = price
                pkg.duration = duration
                pkg.duration_unit = duration_unit
                pkg.user_type = user_type
                updated += 1
            else:
                db.session.add(Package(
                    name=name, speed=speed, price=price,
                    duration=duration, duration_unit=duration_unit, user_type=user_type
                ))
                imported += 1
        db.session.commit()
        log_event('استيراد باقات (API)', f'{imported + updated} باقة',
                  f'جديدة: {imported} | محدّثة: {updated} | متجاهلة: {skipped}', admin_name='النظام (API)')
        return jsonify({
            'ok': True, 'imported': imported, 'updated': updated, 'skipped': skipped,
            'total': len(data),
            'message': f'تم بنجاح: {imported} باقة جديدة، {updated} محدّثة، {skipped} متجاهلة.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============ Traffic API ============

@app.route('/api/traffic/interfaces/<int:router_id>')
def api_get_interfaces(router_id):
    router = Router.query.get_or_404(router_id)
    api = None
    try:
        api = get_mikrotik_api(router)
        interfaces_data = list(api.path('interface'))
        interfaces = []
        for iface in interfaces_data:
            name = _safe_str(iface.get('name'))
            if not name:
                continue
            disabled = _safe_bool(iface.get('disabled'), False)
            if disabled:
                continue
            iface_type = _safe_str(iface.get('type'), 'unknown')
            running = _safe_bool(iface.get('running'), False)
            interfaces.append({'name': name, 'type': iface_type, 'running': running})
        interfaces.sort(key=lambda x: x['name'])
        return jsonify({'ok': True, 'interfaces': interfaces, 'method': 'API', 'count': len(interfaces)})
    except Exception as e:
        logger.error(f"❌ خطأ جلب المنافذ: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        if api:
            try:
                api.close()
            except Exception:
                pass


@app.route('/api/traffic/stats/<int:router_id>/<interface>')
def api_get_traffic_stats(router_id, interface):
    router = Router.query.get_or_404(router_id)
    api = None
    try:
        api = get_mikrotik_api(router)
        interfaces = list(api.path('interface'))
        target = None
        for iface in interfaces:
            if _safe_str(iface.get('name')) == interface:
                target = iface
                break
        if not target:
            return jsonify({'ok': False, 'error': f'المنفذ {interface} غير موجود'}), 404
        rx_byte = _safe_int(target.get('rx-byte', '0'), 0)
        tx_byte = _safe_int(target.get('tx-byte', '0'), 0)
        cache_key = f"{router_id}_{interface}"
        now = time.time()
        rx_rate_bps = tx_rate_bps = 0
        if cache_key in _traffic_cache:
            prev = _traffic_cache[cache_key]
            elapsed = now - prev['time']
            if elapsed > 0:
                rx_diff = max(0, rx_byte - prev['rx_byte'])
                tx_diff = max(0, tx_byte - prev['tx_byte'])
                rx_rate_bps = (rx_diff / elapsed) * 8
                tx_rate_bps = (tx_diff / elapsed) * 8
        _traffic_cache[cache_key] = {'time': now, 'rx_byte': rx_byte, 'tx_byte': tx_byte}
        def format_rate(bps):
            if bps >= 1_000_000_000:
                return f"{bps / 1_000_000_000:.2f}Gbps"
            elif bps >= 1_000_000:
                return f"{bps / 1_000_000:.2f}Mbps"
            elif bps >= 1_000:
                return f"{bps / 1_000:.2f}kbps"
            else:
                return f"{int(bps)}bps"
        stats = {
            'rx_rate': format_rate(rx_rate_bps),
            'tx_rate': format_rate(tx_rate_bps),
            'rx_byte': str(rx_byte),
            'tx_byte': str(tx_byte),
        }
        return jsonify({'ok': True, 'stats': stats, 'method': 'API'})
    except Exception as e:
        logger.error(f"❌ خطأ جلب الترافيك: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        if api:
            try:
                api.close()
            except Exception:
                pass


@app.route('/api/dashboard_data')
def api_dashboard_data():
    try:
        start, end = _day_bounds()
        today_revenue = db.session.query(db.func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.created_at >= start,
            Payment.created_at < end
        ).scalar() or 0
        new_users_today = Subscriber.query.filter(
            Subscriber.created_at >= start,
            Subscriber.created_at < end
        ).count()
        events = SystemEvent.query.order_by(SystemEvent.created_at.desc()).limit(15).all()
        events_data = [{
            'time': e.created_at.astimezone(LOCAL_TZ).strftime('%H:%M'),
            'admin': e.admin_name or 'النظام', 'action': e.action,
            'target': e.target or '-', 'details': e.details or '-'
        } for e in events]
        recent_logs = TelegramLog.query.order_by(TelegramLog.created_at.desc()).limit(5).all()
        logs_data = [{
            'time': l.created_at.astimezone(LOCAL_TZ).strftime('%m-%d %H:%M'),
            'type': l.message_type, 'status': l.status
        } for l in recent_logs]
        return jsonify({
            'routers_count': Router.query.count(),
            'routers_online': Router.query.filter_by(is_active=True).count(),
            'sub_count': Subscriber.query.count(),
            'active_subs': Subscriber.query.filter_by(status='active').count(),
            'online_count': Subscriber.query.filter(
                Subscriber.current_ip.isnot(None), Subscriber.current_ip != ''
            ).count(),
            'today_revenue': f"{today_revenue:.0f}",
            'new_users_today': new_users_today,
            'events': events_data, 'telegram_logs': logs_data
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/telegram_data')
def api_telegram_data():
    try:
        logs = TelegramLog.query.order_by(TelegramLog.created_at.desc()).limit(10).all()
        logs_data = [{
            'time': l.created_at.astimezone(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S'),
            'type': l.message_type, 'status': l.status, 'message': l.message
        } for l in logs]
        return jsonify({
            'total_notifications': TelegramLog.query.count(),
            'new_subscribers': TelegramLog.query.filter_by(message_type='new_subscriber').count(),
            'expired_subscribers': TelegramLog.query.filter_by(message_type='expired_subscriber').count(),
            'bulk_adds': TelegramLog.query.filter_by(message_type='bulk_add').count(),
            'logs': logs_data
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ============ Auth Guard ============

@app.route('/mobile')
def mobile_view():
    return render_template('mobile.html')


@app.before_request
def check_admin_login():
    if request.endpoint is None:
        return
    if request.endpoint.startswith('static'):
        return
    if request.path.startswith('/api/'):
        return
    public = (
        'login', 'logout', 'mobile', 'mobile_view',
        'sync.get_subscribers', 'sync.mark_first_use',
        'api_auth', 'api_log', 'api_router_notify',
        'api_import_subscribers', 'api_import_packages',
        'api_get_interfaces', 'api_get_traffic_stats'
    )
    if request.endpoint in public:
        return
    if not session.get('admin_id'):
        return redirect(url_for('login'))


# ============ Main Routes ============

@app.route('/')
def index():
    return redirect(url_for('dashboard'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username', '').strip()
        p = request.form.get('password', '').strip()
        if not u or not p:
            flash('❌ الرجاء إدخال البيانات', 'danger')
            return redirect(url_for('login'))
        admin = AdminUser.query.filter_by(username=u).first()
        if admin and check_password_hash(admin.password, p):
            session['admin_id'] = admin.id
            session['admin_name'] = admin.username
            log_event('تسجيل دخول', 'لوحة التحكم', 'تسجيل دخول ناجح')
            flash('✅ تم تسجيل الدخول', 'success')
            return redirect(url_for('dashboard'))
        flash('❌ بيانات غير صحيحة', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    log_event('تسجيل خروج', 'لوحة التحكم', 'تسجيل خروج المدير')
    session.clear()
    flash('✅ تم تسجيل الخروج', 'success')
    return redirect(url_for('login'))


@app.route('/import-backup', methods=['GET', 'POST'])
def import_backup():
    if request.method == 'POST':
        try:
            if 'backup_file' not in request.files:
                flash('❌ الرجاء اختيار ملف النسخة الاحتياطية', 'danger')
                return redirect(url_for('import_backup'))
            file = request.files['backup_file']
            if not file.filename:
                flash('❌ لم يتم اختيار أي ملف', 'danger')
                return redirect(url_for('import_backup'))
            if not file.filename.lower().endswith(('.rsc', '.txt')):
                flash('❌ يجب أن يكون الملف بصيغة .rsc أو .txt', 'danger')
                return redirect(url_for('import_backup'))
            raw_bytes = file.read()
            try:
                content = raw_bytes.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    content = raw_bytes.decode('windows-1256')
                except UnicodeDecodeError:
                    content = raw_bytes.decode('utf-8', errors='ignore')
            if content[:5] == 'PK\x03\x04' or raw_bytes[:4] == b'\x00\x00\x00\x00':
                flash('❌ هذا ملف Backup ثنائي وليس RSC!', 'danger')
                return redirect(url_for('import_backup'))
            packages, subscribers, debug_info = parse_mikrotik_rsc(content)
            if not packages and not subscribers:
                preview = debug_info['preview'].replace('\n', '<br>').replace('<', '&lt;').replace('>', '&gt;')[:800]
                sections = ', '.join(debug_info['sections_found']) or 'لا يوجد'
                error_msg = (
                    f'⚠️ لم يتم العثور على بيانات!<br>'
                    f'📄 صيغة الملف: <strong>{debug_info["format"]}</strong><br>'
                    f'📄 عدد الأسطر: {debug_info["lines_read"]}<br>'
                    f'🔍 الأقسام المكتشفة: {sections}<br>'
                    f'📊 أسطر Profiles: {debug_info["profile_lines"]} | أسطر Secrets: {debug_info["secret_lines"]}<br>'
                    f'<br><strong>معاينة أول أسطر الملف:</strong><br>'
                    f'<code style="display:block; max-height:200px; overflow:auto; background:#000; padding:10px; margin-top:5px; text-align:left; direction:ltr; color:#0f0; font-size:11px;">{preview}</code>'
                )
                flash(error_msg, 'warning')
                return redirect(url_for('import_backup'))
            pkg_imported = pkg_updated = 0
            for p in packages:
                existing = Package.query.filter_by(name=p['name']).first()
                if existing:
                    existing.speed = p['speed'] or existing.speed
                    pkg_updated += 1
                else:
                    db.session.add(Package(**p))
                    pkg_imported += 1
            sub_imported = sub_updated = 0
            for s in subscribers:
                existing = Subscriber.query.filter_by(username=s['username']).first()
                if existing:
                    existing.password = s['password']
                    existing.package = s['package']
                    existing.user_type = s['user_type']
                    existing.status = s['status']
                    existing.name = s['name']
                    sub_updated += 1
                else:
                    db.session.add(Subscriber(
                        name=s['name'], username=s['username'], password=s['password'],
                        package=s['package'], user_type=s['user_type'],
                        status=s['status'], expires_at=None
                    ))
                    sub_imported += 1
            db.session.commit()
            log_event(
                'استيراد نسخة احتياطية', f'ملف: {file.filename}',
                f'باقات: {pkg_imported}+{pkg_updated} | مشتركين: {sub_imported}+{sub_updated}',
                admin_name=session.get('admin_name', 'المدير')
            )
            flash(
                f'✅ تم الاستيراد بنجاح! (صيغة: {debug_info["format"]}) | '
                f'📦 الباقات: {pkg_imported} جديدة، {pkg_updated} محدّثة | '
                f'👥 المشتركون: {sub_imported} جديد، {sub_updated} محدّث',
                'success'
            )
            return redirect(url_for('import_backup'))
        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ Backup import error: {e}")
            logger.error(traceback.format_exc())
            flash(f'❌ خطأ في الاستيراد: {str(e)}', 'danger')
            return redirect(url_for('import_backup'))
    return render_template('import_backup.html',
        total_packages=Package.query.count(),
        total_subscribers=Subscriber.query.count()
    )


@app.route('/traffic-monitor')
def traffic_monitor_page():
    routers_list = Router.query.all()
    return render_template('traffic_monitor.html', routers=routers_list)


@app.route('/dashboard')
def dashboard():
    try:
        routers_list = Router.query.all()
        routers_count = len(routers_list)
        routers_online = Router.query.filter_by(is_active=True).count()
        master = Router.query.filter_by(is_master=True).first()
        sub_count = Subscriber.query.count()
        active_subs = Subscriber.query.filter_by(status='active').count()

        start, end = _day_bounds()
        today_revenue = db.session.query(db.func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.created_at >= start,
            Payment.created_at < end
        ).scalar() or 0

        now = datetime.utcnow()
        start_month = datetime(now.year, now.month, 1)
        start_year = datetime(now.year, 1, 1)

        monthly_revenue = db.session.query(db.func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.created_at >= start_month
        ).scalar() or 0

        yearly_revenue = db.session.query(db.func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.created_at >= start_year
        ).scalar() or 0

        inactive_subs = Subscriber.query.filter(
            Subscriber.status.in_(['expired', 'paused'])
        ).all()

        new_users_today = Subscriber.query.filter(
            Subscriber.created_at >= start,
            Subscriber.created_at < end
        ).count()

        pending_pays = Payment.query.filter_by(status='pending').count()
        events_list = SystemEvent.query.order_by(SystemEvent.created_at.desc()).limit(15).all()
        current_time = get_local_time_str()
        telegram_status = TelegramSetting.query.first()
        recent_telegram_logs = TelegramLog.query.order_by(TelegramLog.created_at.desc()).limit(5).all()

        recent_subs = Subscriber.query.order_by(Subscriber.created_at.desc()).limit(5).all()
        recent_payments = Payment.query.filter_by(status='completed').order_by(Payment.created_at.desc()).limit(5).all()
        recent_routers = Router.query.order_by(Router.created_at.desc()).limit(5).all()

        online_subs = Subscriber.query.filter(
            Subscriber.current_ip.isnot(None),
            Subscriber.current_ip != ''
        ).order_by(Subscriber.last_seen_at.desc()).all()
        top_online_subs = online_subs[:10]

        return render_template(
            'dashboard.html',
            routers_count=routers_count,
            routers_online=routers_online,
            routers=routers_list,
            sub_count=sub_count,
            active_subs=active_subs,
            today_revenue=today_revenue,
            monthly_revenue=monthly_revenue,
            yearly_revenue=yearly_revenue,
            inactive_subs=inactive_subs,
            new_users_today=new_users_today,
            has_master=master is not None,
            events=events_list,
            admin_name=session.get('admin_name', 'مدير'),
            current_time=current_time,
            telegram_status=telegram_status,
            recent_telegram_logs=recent_telegram_logs,
            pending_pays=pending_pays,
            active_sessions=0,
            recent_subs=recent_subs,
            recent_payments=recent_payments,
            recent_routers=recent_routers,
            online_subs=online_subs,
            top_online_subs=top_online_subs,
        )
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ dashboard error: {e}")
        flash(f'❌ {str(e)}', 'danger')
        return render_template('error.html', error=str(e)), 500


@app.route('/admin/change-credentials', methods=['POST'])
def change_admin_credentials():
    admin_id = session.get('admin_id')
    if not admin_id:
        flash('❌ غير مصرح', 'danger')
        return redirect(url_for('login'))
    admin = AdminUser.query.get(admin_id)
    if not admin:
        flash('❌ المستخدم غير موجود', 'danger')
        return redirect(url_for('login'))
    try:
        nu = request.form.get('new_username', '').strip()
        cp = request.form.get('current_password', '').strip()
        np = request.form.get('new_password', '').strip()
        cf = request.form.get('confirm_password', '').strip()
        if not cp or not check_password_hash(admin.password, cp):
            flash('❌ كلمة المرور الحالية غير صحيحة', 'danger')
            return redirect(url_for('dashboard'))
        if nu and nu != admin.username:
            if AdminUser.query.filter_by(username=nu).first():
                flash('❌ اسم المستخدم موجود', 'danger')
                return redirect(url_for('dashboard'))
            admin.username = nu
            session['admin_name'] = nu
        if np:
            if np != cf:
                flash('❌ كلمتا المرور غير متطابقتين', 'danger')
                return redirect(url_for('dashboard'))
            if len(np) < 6:
                flash('❌ 6 أحرف على الأقل', 'danger')
                return redirect(url_for('dashboard'))
            admin.password = generate_password_hash(np)
        db.session.commit()
        log_event('تعديل بيانات الحساب', 'المدير', f'تحديث بيانات المدير {admin.username}')
        flash('✅ تم التحديث بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('dashboard'))


@app.route('/routers', methods=['GET', 'POST'])
def routers():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        ip = request.form.get('ip_address', '').strip()
        un = request.form.get('username', '').strip()
        pw = request.form.get('password', '').strip()
        port = request.form.get('port', '22').strip()
        api_port = request.form.get('api_port', '13').strip()
        is_master = request.form.get('is_master') == 'on'
        if not name or not ip:
            flash('❌ الاسم و IP مطلوبان', 'danger')
            return redirect(url_for('routers'))
        if Router.query.filter_by(name=name).first():
            flash('❌ الاسم موجود', 'danger')
            return redirect(url_for('routers'))
        try:
            port = int(port)
        except ValueError:
            port = 22
        try:
            api_port = int(api_port)
        except ValueError:
            api_port = 13
        try:
            if is_master:
                Router.query.update({Router.is_master: False}, synchronize_session=False)
            db.session.add(Router(
                name=name, ip_address=ip, username=un, password=pw,
                port=port, api_port=api_port, is_master=is_master, is_active=True
            ))
            db.session.commit()
            log_event('إضافة راوتر', name, f'IP: {ip} | SSH: {port} | API: {api_port}')
            try:
                notify_admin_action(f"🖥️ إضافة راوتر: `{name}` - IP: `{ip}` (SSH: {port} | API: {api_port})")
            except Exception:
                pass
            flash(f'✅ الراوتر "{name}" أُضيف', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ {str(e)}', 'danger')
        return redirect(url_for('routers'))
    return render_template('routers.html', routers=Router.query.all())


@app.route('/routers/set_master/<int:router_id>')
def set_master_router(router_id):
    try:
        Router.query.update({Router.is_master: False}, synchronize_session=False)
        r = Router.query.get_or_404(router_id)
        r.is_master = True
        db.session.commit()
        log_event('تعيين راوتر رئيسي', r.name)
        try:
            notify_admin_action(f"⭐ تعيين راوتر رئيسي: `{r.name}`")
        except Exception:
            pass
        flash('✅ تم التحديث بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('routers'))


@app.route('/routers/update/<int:router_id>', methods=['POST'])
def update_router(router_id):
    try:
        r = Router.query.get_or_404(router_id)
        name = request.form.get('name', '').strip()
        ip = request.form.get('ip_address', '').strip()
        un = request.form.get('username', '').strip()
        pw = request.form.get('password', '').strip()
        port = request.form.get('port', '22').strip()
        api_port = request.form.get('api_port', '13').strip()
        if not name or not ip:
            flash('❌ الاسم و IP مطلوبان', 'danger')
            return redirect(url_for('routers'))
        if Router.query.filter(Router.name == name, Router.id != router_id).first():
            flash('❌ الاسم موجود', 'danger')
            return redirect(url_for('routers'))
        r.name = name
        r.ip_address = ip
        r.username = un
        if pw:
            r.password = pw
        try:
            r.port = int(port)
        except ValueError:
            r.port = 22
        try:
            r.api_port = int(api_port)
        except ValueError:
            r.api_port = 13
        db.session.commit()
        log_event('تعديل راوتر', name, f'IP: {ip} | SSH: {r.port} | API: {r.api_port}')
        try:
            notify_admin_action(f"✏️ تعديل راوتر: `{name}` - IP: `{ip}`")
        except Exception:
            pass
        flash('✅ تم التحديث بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('routers'))


@app.route('/routers/delete/<int:router_id>')
def delete_router(router_id):
    try:
        r = Router.query.get_or_404(router_id)
        r_name = r.name
        db.session.delete(r)
        db.session.commit()
        log_event('حذف راوتر', r_name)
        try:
            notify_admin_action(f"🗑️ حذف راوتر: `{r_name}`")
        except Exception:
            pass
        flash('✅ تم الحذف بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('routers'))


@app.route('/subscribers')
def subscribers():
    search = request.args.get('q', '').strip()
    ft = request.args.get('type', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 50
    now = datetime.utcnow()
    try:
        expired = Subscriber.query.filter(
            Subscriber.expires_at.isnot(None),
            Subscriber.expires_at < now,
            Subscriber.status == 'active'
        ).all()
        for s in expired:
            s.status = 'expired'
            try:
                kick_subscriber(s)
            except Exception:
                pass
        if expired:
            db.session.commit()
        q = Subscriber.query
        if search:
            q = q.filter(db.or_(
                Subscriber.username.ilike(f'%{search}%'),
                Subscriber.name.ilike(f'%{search}%')
            ))
        if ft in ('pppoe', 'hotspot'):
            q = q.filter_by(user_type=ft)
        pagination = q.order_by(Subscriber.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        subs = pagination.items
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ error subscribers: {e}")
        subs = []
        pagination = None
    return render_template(
        'subscribers.html',
        subscribers=subs,
        pagination=pagination,
        routers={r.id: r for r in Router.query.all()},
        packages=Package.query.order_by(Package.name).all(),
        search=search,
        now=now,
        filter_type=ft
    )


@app.route('/subscribers/sync-now', methods=['POST'])
def sync_subscribers_now():
    try:
        routers = Router.query.all()
        total_updated = 0
        total_checked = 0
        total_online = 0
        errors = []
        for router in routers:
            try:
                active_ips = fetch_active_ips_from_router(router)
                total_checked += len(active_ips)
                for username, info in active_ips.items():
                    sub = Subscriber.query.filter_by(username=username).first()
                    if sub:
                        total_online += 1
                        changed = False
                        if sub.current_ip != info['ip']:
                            sub.current_ip = info['ip']
                            changed = True
                        if sub.router_id != router.id:
                            sub.router_id = router.id
                            changed = True
                        sub.session_uptime = info.get('uptime', '')
                        sub.session_rx_bytes = info.get('rx_bytes', 0)
                        sub.session_tx_bytes = info.get('tx_bytes', 0)
                        if info.get('uptime'):
                            sub.connected_at = _calculate_connected_at(info['uptime'])
                        sub.ip_updated_at = datetime.utcnow()
                        sub.last_seen_at = datetime.utcnow()
                        if changed:
                            total_updated += 1
                db.session.commit()
            except Exception as e:
                errors.append(f"{router.name}: {str(e)}")
                db.session.rollback()
        log_event('مزامنة فورية', f'{total_updated} تحديث',
                  f'فحص {total_checked} | متصل {total_online} | أخطاء {len(errors)}')
        return jsonify({
            'ok': True, 'updated': total_updated, 'checked': total_checked,
            'online': total_online, 'routers': len(routers), 'errors': errors
        })
    except Exception as e:
        logger.error(f"❌ Sync error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/add-subscriber', methods=['GET', 'POST'])
@app.route('/subscribers/add', methods=['GET', 'POST'])
def add_subscriber():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        un = request.form.get('username', '').strip()
        pw = request.form.get('password', '').strip()
        pkg = request.form.get('package', '').strip()
        ut = request.form.get('user_type', 'pppoe').strip()
        if ut not in ('pppoe', 'hotspot'):
            ut = 'pppoe'
        if not un or not pw:
            flash('❌ الاسم وكلمة المرور مطلوبان', 'danger')
            return redirect(url_for('add_subscriber'))
        if Subscriber.query.filter_by(username=un).first():
            flash(f'❌ "{un}" موجود مسبقاً', 'danger')
            return redirect(url_for('add_subscriber'))
        try:
            db.session.add(Subscriber(
                name=name or un, username=un, password=pw, package=pkg,
                user_type=ut, expires_at=None, status='active'
            ))
            db.session.commit()
            if radius_sync:
                try:
                    radius_sync.sync_user(un, pw)
                except Exception:
                    pass
            log_event('إضافة مشترك', un, f'الباقة: {pkg}')
            try:
                notify_new_subscriber(un)
            except Exception:
                pass
            flash(f'✅ المشترك "{un}" أُضيف بنجاح', 'success')
            return redirect(url_for('subscribers'))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ {e}', 'danger')
    return render_template(
        'add_subscriber.html',
        packages=Package.query.order_by(Package.name).all(),
        routers=Router.query.order_by(Router.name).all()
    )


@app.route('/subscribers/bulk-add', methods=['GET', 'POST'])
def bulk_add():
    if request.method == 'POST':
        pkg = request.form.get('package', '').strip()
        ut = request.form.get('user_type', 'pppoe').strip()
        prefix = request.form.get('prefix', '').strip()
        cm = request.form.get('char_mode', 'numbers').strip()
        cnt = request.form.get('count', '1').strip()
        pm = request.form.get('password_mode', 'random')
        fp = request.form.get('fixed_password', '').strip()
        pl = request.form.get('password_length', '6').strip()
        if ut not in ('pppoe', 'hotspot'):
            ut = 'pppoe'
        if cm not in ('numbers', 'letters', 'mixed'):
            cm = 'numbers'
        if pm not in ('random', 'same_as_username', 'fixed'):
            pm = 'random'
        try:
            pl = int(pl)
            if pl < 4 or pl > 20:
                pl = 6
        except ValueError:
            pl = 6
        try:
            rl = int(request.form.get('random_length', '6'))
            if rl < 4 or rl > 20:
                rl = 6
        except ValueError:
            rl = 6
        try:
            cnt = int(cnt)
        except ValueError:
            flash('❌ عدد غير صحيح', 'danger')
            return redirect(url_for('bulk_add'))
        if cnt < 1 or cnt > 500:
            flash('❌ بين 1 و 500', 'danger')
            return redirect(url_for('bulk_add'))
        L = 'abcdefghijkmnpqrstuvwxyz'
        N = '23456789'
        M = L + N
        usernames = []
        if cm == 'numbers':
            for _ in range(cnt):
                usernames.append(f"{prefix}{''.join(random.choices(N, k=rl))}")
        elif cm == 'letters':
            for _ in range(cnt):
                usernames.append(f"{prefix}{''.join(random.choices(L, k=rl))}")
        else:
            for _ in range(cnt):
                usernames.append(f"{prefix}{''.join(random.choices(M, k=rl))}")
        created = failed = 0
        for un in usernames:
            if pm == 'same_as_username':
                pw = un
            elif pm == 'fixed':
                pw = fp
            elif pm == 'random':
                pw = ''.join(random.choices(N, k=pl))
            else:
                pw = un
            if Subscriber.query.filter_by(username=un).first():
                failed += 1
                continue
            try:
                db.session.add(Subscriber(
                    name=un, username=un, password=pw, package=pkg,
                    user_type=ut, expires_at=None, status='active'
                ))
                created += 1
            except Exception:
                db.session.rollback()
                failed += 1
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        if radius_sync:
            for un in usernames:
                sub = Subscriber.query.filter_by(username=un).first()
                if sub:
                    try:
                        radius_sync.sync_user(sub.username, sub.password)
                    except Exception:
                        pass
        log_event('إضافة جملة', f'{created} مشترك', f'الباقة: {pkg}')
        try:
            notify_bulk_add(created, failed, pkg)
        except Exception:
            pass
        flash(
            f'✅ تم إيجاد {created} مشترك' + (f' — فشل {failed}' if failed else ''),
            'success' if not failed else 'warning'
        )
        return redirect(url_for('subscribers'))
    return render_template(
        'bulk_add.html',
        packages=Package.query.order_by(Package.name).all(),
        routers=Router.query.order_by(Router.name).all()
    )


@app.route('/subscribers/toggle/<int:sub_id>')
def toggle_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        if sub.status == 'active':
            sub.status = 'paused'
            db.session.commit()
            if radius_sync:
                try:
                    radius_sync.pause_user(sub.username)
                except Exception:
                    pass
            kick_subscriber(sub)
            log_event('إيقاف مشترك', sub.username)
            flash(f'⏸ "{sub.username}" موقوف وتم قطعه', 'warning')
        else:
            if sub.expires_at and sub.expires_at < datetime.utcnow():
                flash('⚠️ الحساب منتهي الإشتراك', 'danger')
            else:
                sub.status = 'active'
                db.session.commit()
                if radius_sync:
                    try:
                        radius_sync.resume_user(sub.username, sub.password)
                    except Exception:
                        pass
                log_event('تنشيط مشترك', sub.username)
                flash(f'▶ "{sub.username}" نشط الأن', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


@app.route('/subscribers/reset/<int:sub_id>')
def reset_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        sub.expires_at = None
        sub.first_used_at = None
        sub.status = 'active'
        db.session.commit()
        kick_subscriber(sub)
        log_event('تصفير مشترك', sub.username)
        flash('🔄 تم تصفير عداد المشترك بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


@app.route('/subscribers/extend/<int:sub_id>')
def extend_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        pkg = Package.query.filter_by(name=sub.package).first() if sub.package else None
        base = sub.expires_at if sub.expires_at and sub.expires_at > datetime.utcnow() else datetime.utcnow()
        sub.expires_at = calculate_expiry(pkg, base) if pkg else base + timedelta(days=30)
        sub.status = 'active'
        db.session.commit()
        log_event('تتمديد اشتراك', sub.username, f'تاريخ الانتهاء الجديد: {sub.expires_at.strftime("%Y-%m-%d")}')
        flash(f'➕ ينتهي في {sub.expires_at.strftime("%Y-%m-%d")}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


@app.route('/subscribers/update/<int:sub_id>', methods=['POST'])
def update_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        sub.name = request.form.get('name', '').strip() or sub.name
        nun = request.form.get('username', '').strip()
        if nun:
            sub.username = nun
        pw = request.form.get('password', '').strip()
        if pw:
            sub.password = pw
        pkg = request.form.get('package', '').strip()
        if pkg:
            sub.package = pkg
        ut = request.form.get('user_type', '').strip()
        if ut in ('pppoe', 'hotspot'):
            sub.user_type = ut
        days_to_add = request.form.get('days_to_add', type=int)
        if days_to_add and days_to_add > 0:
            if sub.expires_at:
                sub.expires_at = sub.expires_at + timedelta(days=days_to_add)
            else:
                sub.expires_at = datetime.utcnow() + timedelta(days=days_to_add)
        db.session.commit()
        log_event('تعديل مشترك', sub.username)
        flash('✅ تم التحديث في قاعدة البيانات', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


@app.route('/subscribers/delete/<int:sub_id>')
def delete_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        un = sub.username
        kick_subscriber(sub)
        if radius_sync:
            try:
                radius_sync.delete_user(un)
            except Exception:
                pass
        db.session.delete(sub)
        db.session.commit()
        log_event('حذف مشترك', un)
        flash('✅ تم الحذف وقطع الاتصال بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


@app.route('/subscribers/bulk-delete', methods=['POST'])
def bulk_delete_subscribers():
    try:
        ids = request.form.get('ids', '').strip()
        if not ids:
            flash('❌ لم تحدد أي مشترك', 'warning')
            return redirect(url_for('subscribers'))
        ids_list = [int(x) for x in ids.split(',') if x.strip().isdigit()]
        subs = Subscriber.query.filter(Subscriber.id.in_(ids_list)).all()
        deleted = kicked = 0
        for sub in subs:
            try:
                kick_subscriber(sub)
                kicked += 1
            except Exception:
                pass
            if radius_sync:
                try:
                    radius_sync.delete_user(sub.username)
                except Exception:
                    pass
            db.session.delete(sub)
            deleted += 1
        db.session.commit()
        log_event('حذف جملة', f'{deleted} مشترك')
        flash(f'🗑 تم حذف {deleted} مشترك — تم قطع {kicked}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


@app.route('/subscribers/delete-expired', methods=['POST'])
def delete_expired_subscribers():
    try:
        now = datetime.utcnow()
        expired_subs = Subscriber.query.filter(
            Subscriber.expires_at.isnot(None),
            Subscriber.expires_at < now
        ).all()
        extra = Subscriber.query.filter(
            Subscriber.status == 'expired',
            Subscriber.expires_at.is_(None)
        ).all()
        all_expired = list(expired_subs) + list(extra)
        seen = set()
        unique = []
        for s in all_expired:
            if s.id not in seen:
                seen.add(s.id)
                unique.append(s)
        if not unique:
            flash('ℹ️ لا يوجد مشتركين منتهين', 'info')
            return redirect(url_for('subscribers'))
        deleted = 0
        for sub in unique:
            try:
                kick_subscriber(sub)
            except Exception:
                pass
            if radius_sync:
                try:
                    radius_sync.delete_user(sub.username)
                except Exception:
                    pass
            db.session.delete(sub)
            deleted += 1
        db.session.commit()
        log_event('حذف المنتهين', f'{deleted} مشترك')
        flash(f'🗑 تم حذف {deleted} مشترك منتهي', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


@app.route('/subscribers/export/<format>')
def export_subscribers(format):
    ft = request.args.get('type', '').strip()
    ids = request.args.get('ids', '').strip()
    if ids:
        try:
            idl = [int(x) for x in ids.split(',') if x.strip().isdigit()]
            subs = Subscriber.query.filter(Subscriber.id.in_(idl)).order_by(Subscriber.created_at.desc()).all()
        except Exception:
            subs = []
    else:
        q = Subscriber.query
        if ft in ('pppoe', 'hotspot'):
            q = q.filter_by(user_type=ft)
        subs = q.order_by(Subscriber.created_at.desc()).all()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if format == 'csv':
        out = io.StringIO()
        out.write('\ufeff')
        w = csv.writer(out)
        w.writerow(['#', 'الاسم', 'المستخدم', 'كلمة المرور', 'الباقة', 'النوع', 'الحالة', 'IP', 'تاريخ الانتهاء'])
        for i, s in enumerate(subs, 1):
            w.writerow([
                i, s.name or '', s.username, s.password,
                s.package or '', s.user_type or 'pppoe',
                s.status or 'active', s.current_ip or '',
                s.expires_at.strftime('%Y-%m-%d %H:%M') if s.expires_at else 'غير محدد'
            ])
        mem = io.BytesIO()
        mem.write(out.getvalue().encode('utf-8'))
        mem.seek(0)
        return send_file(
            mem, mimetype='text/csv', as_attachment=True,
            download_name=f'subscribers_{ts}.csv'
        )
    return redirect(url_for('subscribers'))


@app.route('/packages', methods=['GET', 'POST'])
def packages():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        speed = request.form.get('speed', '').strip()
        price = request.form.get('price', '0').strip()
        duration = request.form.get('duration', '30').strip()
        unit = request.form.get('duration_unit', 'days').strip()
        ut = request.form.get('user_type', 'pppoe').strip()
        if not name:
            flash('❌ اسم الباقة مطلوب', 'danger')
            return redirect(url_for('packages'))
        if Package.query.filter_by(name=name).first():
            flash('❌ اسم الباقة موجود بالفعل', 'danger')
            return redirect(url_for('packages'))
        try:
            p_val = float(price) if price else 0
            d_val = int(duration) if duration else 30
            db.session.add(Package(
                name=name, speed=speed, price=p_val,
                duration=d_val, duration_unit=unit, user_type=ut
            ))
            db.session.commit()
            log_event('إضافة باقة', name, f'السعر: {p_val}')
            flash(f'✅ الباقة "{name}" أُضيفت بنجاح', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ {str(e)}', 'danger')
        return redirect(url_for('packages'))
    pkgs = Package.query.order_by(Package.created_at.desc()).all()
    return render_template('packages.html', packages=pkgs)


@app.route('/packages/update/<int:pkg_id>', methods=['POST'])
def update_package(pkg_id):
    try:
        pkg = Package.query.get_or_404(pkg_id)
        pkg.name = request.form.get('name', '').strip() or pkg.name
        pkg.speed = request.form.get('speed', '').strip() or pkg.speed
        pkg.price = float(request.form.get('price', pkg.price))
        pkg.duration = int(request.form.get('duration', pkg.duration))
        pkg.duration_unit = request.form.get('duration_unit', 'days').strip()
        pkg.user_type = request.form.get('user_type', 'pppoe').strip()
        db.session.commit()
        log_event('تعديل باقة', pkg.name, f'السعر: {pkg.price}')
        flash('✅ تم تحديث الباقة بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('packages'))


@app.route('/packages/delete/<int:pkg_id>')
def delete_package(pkg_id):
    try:
        pkg = Package.query.get_or_404(pkg_id)
        pkg_name = pkg.name
        db.session.delete(pkg)
        db.session.commit()
        log_event('حذف باقة', pkg_name)
        flash('✅ تم حذف الباقة بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('packages'))


@app.route('/admin-settings', methods=['GET'])
def admin_settings():
    settings = TelegramSetting.query.first()
    if not settings:
        settings = TelegramSetting(
            enabled=False, notify_new_subscriber=True, notify_subscriber_expired=True,
            notify_bulk_add=True, notify_admin_action=False, notify_router_status=True
        )
    logs = TelegramLog.query.order_by(TelegramLog.created_at.desc()).limit(10).all()
    total_notifications = TelegramLog.query.count()
    new_subscribers = TelegramLog.query.filter_by(message_type='new_subscriber').count()
    expired_subscribers = TelegramLog.query.filter_by(message_type='expired_subscriber').count()
    bulk_adds = TelegramLog.query.filter_by(message_type='bulk_add').count()
    return render_template(
        'admin_settings.html',
        telegram_settings=settings,
        telegram_logs=logs,
        total_notifications=total_notifications,
        new_subscribers=new_subscribers,
        expired_subscribers=expired_subscribers,
        bulk_adds=bulk_adds
    )


@app.route('/admin-settings/save', methods=['POST'])
def save_telegram_settings():
    settings = TelegramSetting.query.first()
    if not settings:
        settings = TelegramSetting()
    settings.token = request.form.get('telegram_token', '').strip()
    settings.chat_id = request.form.get('telegram_chat_id', '').strip()
    settings.enabled = 'telegram_enabled' in request.form
    settings.notify_new_subscriber = 'notify_new_subscriber' in request.form
    settings.notify_subscriber_expired = 'notify_subscriber_expired' in request.form
    settings.notify_bulk_add = 'notify_bulk_add' in request.form
    settings.notify_admin_action = 'notify_admin_action' in request.form
    settings.notify_router_status = 'notify_router_status' in request.form
    db.session.add(settings)
    db.session.commit()
    flash('✅ تم حفظ إعدادات التلجرام بنجاح', 'success')
    return redirect(url_for('admin_settings'))


@app.route('/admin-settings/test', methods=['POST'])
def test_telegram():
    settings = TelegramSetting.query.first()
    if not settings or not settings.token or not settings.chat_id:
        return jsonify({'success': False, 'error': 'الإعدادات غير مكتملة'})
    ok, msg = send_telegram_message(
        "✅ *اختبار الإشعار*\nتم إرسال رسالة اختبار بنجاح من النظام",
        message_type='test', force=True
    )
    if ok:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': msg})


@app.route('/payments')
def payments():
    pay_list = Payment.query.order_by(Payment.created_at.desc()).all()
    return render_template('payments.html', payments=pay_list)


# ============ Main ============

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
