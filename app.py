import os
import socket
import logging
from datetime import datetime, timedelta
import calendar

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, session
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import paramiko

# إعداد السجلات
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'zinar-secret-key-2026')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

# إعداد قاعدة البيانات (يدعم PostgreSQL على Render و SQLite محلياً)
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

db = SQLAlchemy(app)

# ============ نماذج قاعدة البيانات (Models) ============

class Router(db.Model):
    __tablename__ = 'routers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    ip_address = db.Column(db.String(50), nullable=False)  # مثال: 10.10.10.1
    username = db.Column(db.String(50), nullable=False, default='admin')
    password = db.Column(db.String(150), nullable=False)
    port = db.Column(db.Integer, default=8728)
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


# ============ دوال المساعدة (Helpers) ============

def log_event(action, target="", details="", admin_name=None):
    try:
        if not admin_name:
            admin_name = session.get('admin_name', 'النظام')
        evt = SystemEvent(admin_name=admin_name, action=action, target=target, details=details)
        db.session.add(evt)
        db.session.commit()
    except Exception as e:
        logger.warning(f"⚠️ فشل تسجيل الحدث: {e}")

# فحص اتصال الراوتر عبر السوكت (VPN) بأمان تام ودون تعليق
def check_router_status(ip, port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)  # مهلة زمنية قصيرة لمنع أي تعليق للخادم
        result = sock.connect_ex((str(ip), int(port or 8728)))
        sock.close()
        return result == 0
    except Exception:
        return False

def _day_bounds():
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


# ============ تهيئة قاعدة البيانات والتأكد من الأعمدة ============

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
            logger.info("✅ تم تهيئة قاعدة البيانات بنجاح")
        except Exception as e:
            logger.error(f"❌ خطأ في تهيئة قاعدة البيانات: {e}")

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
                    if 'is_master' not in cols:
                        conn.execute(text("ALTER TABLE routers ADD COLUMN is_master BOOLEAN DEFAULT FALSE"))
                conn.commit()
            logger.info("✅ فحص الأعمدة وتحديثها اكتمل")
        except Exception as e:
            logger.warning(f"⚠️ ensure_columns: {e}")

init_database()
ensure_columns()


# ============ حماية الجلسة (Auth Guard) ============

@app.before_request
def check_admin_login():
    if request.endpoint is None: return
    if request.endpoint.startswith('static'): return
    if request.path.startswith('/api/'): return
    public = ('login', 'logout', 'mobile_view')
    if request.endpoint in public: return
    if not session.get('admin_id'):
        return redirect(url_for('login'))


# ============ المسارات الأساسية (Routes) ============

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


# ============ لوحة التحكم (Dashboard) ============

@app.route('/dashboard')
def dashboard():
    try:
        routers_list = []
        routers_online = 0
        try:
            routers_list = Router.query.all()
            for r in routers_list:
                try:
                    r.is_active = check_router_status(r.ip_address, r.port)
                    if r.is_active:
                        routers_online += 1
                except:
                    r.is_active = False
            db.session.commit()
        except:
            db.session.rollback()

        routers_count = len(routers_list)
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
        return render_template('dashboard.html', routers=[], routers_count=0, routers_online=0, has_master=False, sub_count=0, active_subs=0, today_revenue=0, new_users_today=0, events=[], admin_name='مدير')


# ============ إدارة الراوترات والسيرفرات (Routers) ============

@app.route('/routers', methods=['GET', 'POST'])
def routers():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            ip = request.form.get('ip_address', '').strip()
            un = request.form.get('username', '').strip()
            pw = request.form.get('password', '').strip()
            port = request.form.get('port', '8728').strip()
            is_master = True if request.form.get('is_master') else False

            if not name or not ip:
                flash('❌ اسم السيرفر وعنوان IP مطلوبان', 'danger')
                return redirect(url_for('routers'))

            if Router.query.filter_by(name=name).first():
                flash('❌ اسم السيرفر موجود مسبقاً', 'danger')
                return redirect(url_for('routers'))

            try: 
                port = int(port)
            except ValueError: 
                port = 8728

            if is_master:
                Router.query.update({Router.is_master: False})

            # فحص الاتصال بالـ VPN
            is_active = check_router_status(ip, port)

            new_router = Router(
                name=name, ip_address=ip, username=un,
                password=pw, port=port, is_master=is_master, is_active=is_active
            )
            db.session.add(new_router)
            db.session.commit()
            
            log_event('إضافة سيرفر', name, f'IP: {ip}')
            flash(f'✅ تم إضافة السيرفر "{name}" بنجاح', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ حدث خطأ: {str(e)}', 'danger')
        return redirect(url_for('routers'))

    # جلب الراوترات وفحص حالتها بأمان تام
    all_routers = []
    try:
        all_routers = Router.query.all()
        for r in all_routers:
            try:
                r.is_active = check_router_status(r.ip_address, r.port)
            except:
                r.is_active = False
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ routers get error: {e}")

    return render_template('routers.html', routers=all_routers)

@app.route('/routers/set_master/<int:router_id>')
@app.route('/routers/master/<int:router_id>')
def set_master_router(router_id):
    try:
        Router.query.update({Router.is_master: False})
        r = Router.query.get_or_404(router_id)
        r.is_master = True
        db.session.commit()
        log_event('تعيين سيرفر رئيسي', r.name)
        flash(f'✅ تم تعيين {r.name} كـ سيرفر رئيسي', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('routers'))

@app.route('/routers/toggle/<int:router_id>')
def toggle_router(router_id):
    try:
        r = Router.query.get_or_404(router_id)
        r.is_active = not r.is_active
        db.session.commit()
        flash('✅ تم تغيير حالة السيرفر', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('routers'))

@app.route('/routers/test/<int:router_id>')
def test_router(router_id):
    try:
        r = Router.query.get_or_404(router_id)
        r.is_active = check_router_status(r.ip_address, r.port)
        db.session.commit()
        if r.is_active:
            flash(f'🟢 الاتصال بالسيرفر {r.name} ({r.ip_address}) ناجح!', 'success')
        else:
            flash(f'🔴 تعذر الاتصال بالسيرفر {r.name} عبر الـ IP ({r.ip_address})', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ في اختبار الاتصال: {str(e)}', 'danger')
    return redirect(url_for('routers'))

@app.route('/routers/update/<int:router_id>', methods=['POST'])
def update_router(router_id):
    try:
        r = Router.query.get_or_404(router_id)
        name = request.form.get('name', '').strip()
        ip = request.form.get('ip_address', '').strip()
        un = request.form.get('username', '').strip()
        pw = request.form.get('password', '').strip()
        port = request.form.get('port', '8728').strip()

        if not name or not ip:
            flash('❌ الاسم و IP مطلوبان', 'danger')
            return redirect(url_for('routers'))

        r.name = name
        r.ip_address = ip
        r.username = un
        if pw: 
            r.password = pw
        try: 
            r.port = int(port)
        except ValueError: 
            r.port = 8728

        r.is_active = check_router_status(r.ip_address, r.port)
        db.session.commit()
        
        log_event('تعديل سيرفر', name, f'IP: {ip}')
        flash('✅ تم تحديث بيانات السيرفر بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('routers'))

@app.route('/routers/delete/<int:router_id>')
def delete_router(router_id):
    try:
        r = Router.query.get_or_404(router_id)
        name = r.name
        db.session.delete(r)
        db.session.commit()
        log_event('حذف سيرفر', name)
        flash('✅ تم حذف السيرفر بنجاح', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('routers'))

@app.route('/router_users/<int:router_id>')
def router_users(router_id):
    router = Router.query.get_or_404(router_id)
    return render_template('router_users.html', router=router, users=[])


# ============ أقسام أخرى (Subscribers, Packages, Payments) ============

@app.route('/subscribers')
def subscribers():
    try:
        subs = Subscriber.query.order_by(Subscriber.created_at.desc()).all()
    except:
        subs = []
    return render_template('subscribers.html', subscribers=subs)

@app.route('/packages')
def packages():
    try:
        pkgs = Package.query.all()
    except:
        pkgs = []
    return render_template('packages.html', packages=pkgs)

@app.route('/payments')
def payments():
    try:
        pays = Payment.query.all()
    except:
        pays = []
    return render_template('payments.html', payments=pays)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
