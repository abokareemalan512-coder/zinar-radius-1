import os
import io
import csv
import random
import string
import logging
import traceback
import calendar
from datetime import datetime, timedelta

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

# محاولة استيراد radius_sync مع حماية في حال عدم وجود الموديول
try:
    import radius_sync
except ImportError:
    radius_sync = None

# ============ الإعدادات ============

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'zinar-secret-key-2024')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

_masked = database_url.split('@')[-1] if '@' in database_url else database_url
logger.info(f"📊 DB: ...@{_masked}")

db = SQLAlchemy(app)

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


import requests
from flask import request, jsonify

# 1. دالة إرسال الرسائل (صندوق المرسل - Outbox)
def send_telegram_message(text, message_type='test', force=False):
    try:
        settings = TelegramSetting.query.first()
        if not settings or (not settings.enabled and not force):
            return False, "التليجرام معطل"
        
        token = settings.token
        chat_id = settings.chat_id
        
        if not token or not chat_id:
            return False, "التوكن أو معرف المحادثة غير موجود"
            
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'Markdown'
        }
        
        response = requests.post(url, json=payload, timeout=10)
        res_data = response.json()
        
        if res_data.get('ok'):
            # تسجيل الرسالة المرسلة بنجاح
            log = TelegramLog(
                message_type=message_type,
                status='success',
                message=text
            )
            db.session.add(log)
            db.session.commit()
            return True, "تم الإرسال بنجاح"
        else:
            error_desc = res_data.get('description', 'خطأ غير معروف')
            log = TelegramLog(
                message_type=message_type,
                status='failed',
                message=f"فشل الإرسال: {error_desc}"
            )
            db.session.add(log)
            db.session.commit()
            return False, error_desc
    except Exception as e:
        log = TelegramLog(
            message_type=message_type,
            status='failed',
            message=f"خطأ الاتصال: {str(e)}"
        )
        db.session.add(log)
        db.session.commit()
        return False, str(e)


# 2. مسار استقبال الرسائل (الصندوق الوارد - Inbox Webhook)
@app.route('/api/telegram/webhook', methods=['POST'])
def telegram_webhook():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'ok': True})
        
        msg = data.get('message')
        if msg:
            chat_id = msg.get('chat', {}).get('id')
            text = msg.get('text', '')
            user_info = msg.get('from', {})
            user_name = user_info.get('username') or user_info.get('first_name', 'مستخدم')
            
            # تخزين الرسالة الواردة في السجلات بنوع 'incoming'
            log = TelegramLog(
                message_type='incoming',
                status='success',
                message=f"📥 من: {user_name} (ID: {chat_id})\n💬 النص: {text}"
            )
            db.session.add(log)
            db.session.commit()
            
            # رد تلقائي اختياري عند إرسال /start
            if text.strip() == '/start':
                send_telegram_message(
                    f"أهلاً بك يا {user_name} 👋\nتم استلام رسالتك وربط حسابك بنجاح مع النظام.",
                    message_type='reply',
                    force=True
                )
                
        return jsonify({'ok': True})
    except Exception as e:
        print(f"Webhook Error: {e}")
        return jsonify({'ok': False}), 500


# ============ Helpers ============

def log_event(action, target="", details="", admin_name=None):
    try:
        if not admin_name:
            admin_name = session.get('admin_name', 'النظام')
        evt = SystemEvent(admin_name=admin_name, action=action, target=target, details=details)
        db.session.add(evt)
        db.session.commit()
    except Exception as e:
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
        logger.warning(f"⚠️ فشل تسجيل log تليجرام: {e}")


def send_telegram_message(message, message_type='info', force=False):
    if not requests:
        logger.warning("⚠️ مكتبة requests غير مثبتة")
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
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

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
        logger.warning(f"⚠️ فشل إرسال رسالة تلجرام: {e}")
        return False, str(e)


def notify_new_subscriber(username):
    settings = get_telegram_settings()
    if not settings or not settings.enabled or not settings.notify_new_subscriber:
        return False
    if not settings.token or not settings.chat_id:
        return False
    msg = f"*🆕 مشترك جديد*\n👤 المستخدم: `{username}`\n🕒 الوقت: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
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


# ============ Kick via SSH ============

def kick_user_via_ssh(router, username, user_type='pppoe'):
    if not router:
        return False, "no router"

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=router.ip_address,
            port=router.port or 22,
            username=router.username,
            password=router.password,
            timeout=8,
            allow_agent=False,
            look_for_keys=False,
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
        Router.is_active == True,
        Router.id != (sub.router_id or 0)
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
            
            # تأكد من وجود إعدادات التلجرام الافتراضية
            if not TelegramSetting.query.first():
                db.session.add(TelegramSetting(
                    enabled=False,
                    notify_new_subscriber=True,
                    notify_subscriber_expired=True,
                    notify_bulk_add=True,
                    notify_admin_action=False
                ))
                db.session.commit()
            
            logger.info("✅ تم تهيئة قاعدة البيانات")
        except Exception as e:
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

                if 'subscribers' in tables:
                    cols = [c['name'] for c in insp.get_columns('subscribers')]
                    for col, sql in [
                        ('name', "ALTER TABLE subscribers ADD COLUMN name VARCHAR(100)"),
                        ('user_type', "ALTER TABLE subscribers ADD COLUMN user_type VARCHAR(20) DEFAULT 'pppoe'"),
                        ('first_used_at', "ALTER TABLE subscribers ADD COLUMN first_used_at TIMESTAMP"),
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
        'result': 'allow',
        'profile': profile,
        'expires': expires_str,
        'user_type': sub.user_type or 'pppoe',
        'name': sub.name or sub.username
    })


@app.route('/api/log', methods=['POST'])
def api_log():
    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    logger.info(f"📡 Mikrotik: {data}")
    return jsonify({'ok': True})


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
        'api_auth', 'api_log'
    )
    if request.endpoint in public:
        return
    if not session.get('admin_id'):
        return redirect(url_for('login'))


# ============ Routes ============

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


# ============ Dashboard ============

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

        new_users_today = Subscriber.query.filter(
            Subscriber.created_at >= start,
            Subscriber.created_at < end
        ).count()

        events_list = SystemEvent.query.order_by(SystemEvent.created_at.desc()).limit(20).all()

        return render_template(
            'dashboard.html',
            routers_count=routers_count,
            routers_online=routers_online,
            routers=routers_list,
            sub_count=sub_count,
            active_subs=active_subs,
            today_revenue=today_revenue,
            new_users_today=new_users_today,
            has_master=master is not None,
            events=events_list,
            admin_name=session.get('admin_name', 'مدير'),
        )
    except Exception as e:
        logger.error(f"❌ dashboard error: {e}")
        flash(f'❌ {str(e)}', 'danger')
        return render_template('error.html', error=str(e)), 500


# ============ Admin Profile ============

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


# ============ Routers ============

@app.route('/routers', methods=['GET', 'POST'])
def routers():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        ip = request.form.get('ip_address', '').strip()
        un = request.form.get('username', '').strip()
        pw = request.form.get('password', '').strip()
        port = request.form.get('port', '22').strip()
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
            if is_master:
                Router.query.update({Router.is_master: False}, synchronize_session=False)
            db.session.add(Router(
                name=name,
                ip_address=ip,
                username=un,
                password=pw,
                port=port,
                is_master=is_master,
                is_active=True
            ))
            db.session.commit()
            log_event('إضافة راوتر', name, f'IP: {ip}')
            try:
                notify_admin_action(f"🖥️ إضافة راوتر: `{name}` - IP: `{ip}`")
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

        db.session.commit()
        log_event('تعديل راوتر', name, f'IP: {ip}')
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


# ============ Subscribers ============

@app.route('/subscribers')
def subscribers():
    search = request.args.get('q', '').strip()
    ft = request.args.get('type', '').strip()
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

        subs = q.order_by(Subscriber.created_at.desc()).all()
    except Exception as e:
        logger.error(f"❌ error subscribers: {e}")
        subs = []

    return render_template(
        'subscribers.html',
        subscribers=subs,
        routers={r.id: r for r in Router.query.all()},
        packages=Package.query.order_by(Package.name).all(),
        search=search,
        now=now,
        filter_type=ft
    )


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
                name=name or un,
                username=un,
                password=pw,
                package=pkg,
                user_type=ut,
                expires_at=None,
                status='active'
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
                    name=un,
                    username=un,
                    password=pw,
                    package=pkg,
                    user_type=ut,
                    expires_at=None,
                    status='active'
                ))
                created += 1
            except Exception:
                failed += 1

        db.session.commit()

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
        deleted = 0
        kicked = 0
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
        w.writerow(['#', 'الاسم', 'المستخدم', 'كلمة المرور', 'الباقة', 'النوع', 'الحالة', 'تاريخ الانتهاء'])
        for i, s in enumerate(subs, 1):
            w.writerow([
                i,
                s.name or '',
                s.username,
                s.password,
                s.package or '',
                s.user_type or 'pppoe',
                s.status or 'active',
                s.expires_at.strftime('%Y-%m-%d %H:%M') if s.expires_at else 'غير محدد'
            ])

        mem = io.BytesIO()
        mem.write(out.getvalue().encode('utf-8'))
        mem.seek(0)

        return send_file(
            mem,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'subscribers_{ts}.csv'
        )

    return redirect(url_for('subscribers'))


# ============ Packages ============

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
                name=name,
                speed=speed,
                price=p_val,
                duration=d_val,
                duration_unit=unit,
                user_type=ut
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


# ============ Telegram Admin Settings ============

@app.route('/admin-settings', methods=['GET'])
def admin_settings():
    settings = TelegramSetting.query.first()
    if not settings:
        settings = TelegramSetting(
            enabled=False,
            notify_new_subscriber=True,
            notify_subscriber_expired=True,
            notify_bulk_add=True,
            notify_admin_action=False
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
        message_type='test',
        force=True
    )

    if ok:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': msg})


# ============ Payments ============

@app.route('/payments')
def payments():
    pay_list = Payment.query.order_by(Payment.created_at.desc()).all()
    return render_template('payments.html', payments=pay_list)


# ============ Main ============

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
