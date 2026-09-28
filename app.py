# app.py
import os
import io
import csv
import random
import string
import logging
import traceback
import calendar
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, session, send_file, make_response
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import paramiko
import socket
from mikrotik_api import MikrotikAPI, MikrotikError, get_router_api, test_router_connection

# ============ الإعدادات الأساسية ============
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'zinar-secret-key-2024')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ إعدادات Database ============
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

_masked_url = database_url.split('@')[-1] if '@' in database_url else database_url
logger.info(f"📊 قاعدة البيانات: ...@{_masked_url}")

db = SQLAlchemy(app)

# ============ نماذج قاعدة البيانات ============

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
    router_id = db.Column(db.Integer, db.ForeignKey('routers.id'))
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)


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


# ============ دوال مساعدة ============

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


# ============ تهيئة قاعدة البيانات ============

def init_database():
    with app.app_context():
        try:
            db.create_all()
            if not AdminUser.query.filter_by(username='admin').first():
                admin = AdminUser(
                    username='admin',
                    password=generate_password_hash('admin123'),
                    email='admin@zinar.com'
                )
                db.session.add(admin)
                db.session.commit()
            logger.info("✅ تم تهيئة قاعدة البيانات")
        except Exception as e:
            logger.error(f"❌ خطأ في قاعدة البيانات: {e}")
            logger.error(traceback.format_exc())


def ensure_columns():
    with app.app_context():
        try:
            from sqlalchemy import text, inspect
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()

            with db.engine.connect() as conn:
                if 'routers' in existing_tables:
                    cols = [c['name'] for c in inspector.get_columns('routers')]
                    if 'is_active' not in cols:
                        conn.execute(text("ALTER TABLE routers ADD COLUMN is_active BOOLEAN DEFAULT TRUE"))
                        logger.info("✅ routers.is_active")

                if 'subscribers' in existing_tables:
                    cols = [c['name'] for c in inspector.get_columns('subscribers')]
                    if 'name' not in cols:
                        conn.execute(text("ALTER TABLE subscribers ADD COLUMN name VARCHAR(100)"))
                        logger.info("✅ subscribers.name")
                    if 'user_type' not in cols:
                        conn.execute(text("ALTER TABLE subscribers ADD COLUMN user_type VARCHAR(20) DEFAULT 'pppoe'"))
                        logger.info("✅ subscribers.user_type")

                if 'packages' in existing_tables:
                    cols = [c['name'] for c in inspector.get_columns('packages')]
                    if 'duration_unit' not in cols:
                        conn.execute(text("ALTER TABLE packages ADD COLUMN duration_unit VARCHAR(10) DEFAULT 'days'"))
                        logger.info("✅ packages.duration_unit")
                    if 'user_type' not in cols:
                        conn.execute(text("ALTER TABLE packages ADD COLUMN user_type VARCHAR(20) DEFAULT 'pppoe'"))
                        logger.info("✅ packages.user_type")

                conn.commit()
            logger.info("✅ فحص الأعمدة اكتمل")
        except Exception as e:
            logger.warning(f"⚠️ ensure_columns: {e}")


init_database()
ensure_columns()


def test_mikrotik_connection(router):
    try:
        success, _ = test_router_connection(router)
        return success
    except Exception as e:
        logger.warning(f"⚠️ فشل الاتصال بـ {router.name}: {e}")
        return False


def get_master_router():
    try:
        return Router.query.filter_by(is_master=True).first()
    except Exception:
        return None


def _day_bounds(day=None):
    if day is None:
        day = datetime.utcnow()
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


# ============ حماية المسارات ============

@app.before_request
def check_admin_login():
    if request.endpoint is None:
        return
    if request.endpoint.startswith('static'):
        return
    public_endpoints = {'login', 'logout'}
    if request.endpoint in public_endpoints:
        return
    if not session.get('admin_id'):
        return redirect(url_for('login'))


# ============ الصفحة الرئيسية والدخول ============

@app.route('/')
def index():
    return redirect(url_for('dashboard'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            flash('❌ الرجاء إدخال البيانات', 'danger')
            return redirect(url_for('login'))

        admin = AdminUser.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password, password):
            session['admin_id'] = admin.id
            session['admin_name'] = admin.username
            flash('✅ تم تسجيل الدخول', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('❌ بيانات غير صحيحة', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('✅ تم تسجيل الخروج', 'success')
    return redirect(url_for('login'))


# ============ لوحة التحكم ============

@app.route('/dashboard')
def dashboard():
    try:
        routers_list = Router.query.all()
        routers_count = len(routers_list)
        routers_online = sum(1 for r in routers_list if r.is_active and test_mikrotik_connection(r))

        master = get_master_router()
        sub_count = Subscriber.query.count()
        active_subs = Subscriber.query.filter_by(status='active').count()
        pending_pays = Payment.query.filter_by(status='pending').count()

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

        subscribers_preview = Subscriber.query.order_by(Subscriber.created_at.desc()).limit(8).all()

        return render_template(
            'dashboard.html',
            routers_count=routers_count, routers_online=routers_online,
            sub_count=sub_count, active_subs=active_subs, active_sessions=active_subs,
            today_revenue=today_revenue, active_vouchers=0,
            new_users_today=new_users_today, pending_pays=pending_pays,
            subscribers=subscribers_preview, has_master=master is not None,
            admin_name=session.get('admin_name', 'مدير'),
        )
    except Exception as e:
        logger.error(f"❌ dashboard: {e}")
        flash(f'❌ خطأ: {str(e)}', 'danger')
        return render_template('error.html', error=str(e)), 500


# ============ إدارة حساب المدير ============

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
        new_username = request.form.get('new_username', '').strip()
        current_password = request.form.get('current_password', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        if not current_password or not check_password_hash(admin.password, current_password):
            flash('❌ كلمة المرور الحالية غير صحيحة', 'danger')
            return redirect(url_for('dashboard'))

        if new_username and new_username != admin.username:
            if AdminUser.query.filter_by(username=new_username).first():
                flash('❌ اسم المستخدم موجود', 'danger')
                return redirect(url_for('dashboard'))
            admin.username = new_username
            session['admin_name'] = new_username

        if new_password:
            if new_password != confirm_password:
                flash('❌ كلمتا المرور غير متطابقتين', 'danger')
                return redirect(url_for('dashboard'))
            if len(new_password) < 6:
                flash('❌ 6 أحرف على الأقل', 'danger')
                return redirect(url_for('dashboard'))
            admin.password = generate_password_hash(new_password)

        db.session.commit()
        flash('✅ تم التحديث', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('dashboard'))


# ============ الراوترات ============

@app.route('/routers', methods=['GET', 'POST'])
def routers():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        ip_address = request.form.get('ip_address', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        port = request.form.get('port', '22').strip()
        is_master = request.form.get('is_master') == 'on'

        if not name or not ip_address:
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

            new_router = Router(
                name=name, ip_address=ip_address, username=username,
                password=password, port=port, is_master=is_master, is_active=True
            )
            db.session.add(new_router)
            db.session.commit()

            if test_mikrotik_connection(new_router):
                flash(f'✅ الراوتر "{name}" متصل', 'success')
            else:
                flash('⚠️ تمت الإضافة لكن الاتصال فشل', 'warning')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')
        return redirect(url_for('routers'))

    routers_list = Router.query.all()
    return render_template('routers.html', routers=routers_list)


@app.route('/routers/set_master/<int:router_id>')
def set_master_router(router_id):
    try:
        Router.query.update({Router.is_master: False}, synchronize_session=False)
        router = Router.query.get_or_404(router_id)
        router.is_master = True
        db.session.commit()
        flash('✅ تم التحديث', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('routers'))


@app.route('/routers/toggle/<int:router_id>')
def toggle_router(router_id):
    try:
        router = Router.query.get_or_404(router_id)
        router.is_active = not router.is_active
        db.session.commit()
        state = "تشغيل" if router.is_active else "إيقاف"
        flash(f'✅ تم {state}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('routers'))


@app.route('/routers/update/<int:router_id>', methods=['POST'])
def update_router(router_id):
    try:
        router = Router.query.get_or_404(router_id)
        name = request.form.get('name', '').strip()
        ip_address = request.form.get('ip_address', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        port = request.form.get('port', '22').strip()

        if not name or not ip_address:
            flash('❌ الاسم و IP مطلوبان', 'danger')
            return redirect(url_for('routers'))

        existing = Router.query.filter(Router.name == name, Router.id != router_id).first()
        if existing:
            flash('❌ الاسم موجود', 'danger')
            return redirect(url_for('routers'))

        router.name = name
        router.ip_address = ip_address
        router.username = username
        if password:
            router.password = password
        try:
            router.port = int(port)
        except ValueError:
            router.port = 22

        db.session.commit()
        flash(f'✅ تم التحديث', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('routers'))


@app.route('/routers/test/<int:router_id>')
def test_router(router_id):
    try:
        router = Router.query.get_or_404(router_id)
        if test_mikrotik_connection(router):
            flash(f'✅ الاتصال ناجح', 'success')
        else:
            flash(f'⚠️ فشل الاتصال', 'warning')
    except Exception as e:
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('routers'))


@app.route('/routers/delete/<int:router_id>')
def delete_router(router_id):
    try:
        router = Router.query.get_or_404(router_id)
        db.session.delete(router)
        db.session.commit()
        flash('✅ تم الحذف', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('routers'))


@app.route('/routers/<int:router_id>/users')
def router_users(router_id):
    router = Router.query.get_or_404(router_id)
    user_type = request.args.get('type', 'pppoe')

    users = []
    actives = []
    profiles = []
    error = None

    try:
        api = get_router_api(router)
        if user_type == 'hotspot':
            users = api.hotspot_list()
            actives = api.hotspot_active()
            profiles = api.profiles_list('hotspot')
        else:
            users = api.pppoe_list()
            actives = api.pppoe_active()
            profiles = api.profiles_list('pppoe')
    except MikrotikError as e:
        error = str(e)
    except Exception as e:
        error = f"خطأ: {str(e)}"

    return render_template(
        'router_users.html',
        router=router, users=users, actives=actives,
        profiles=profiles, error=error, user_type=user_type
    )


@app.route('/routers/<int:router_id>/sync')
def sync_router(router_id):
    router = Router.query.get_or_404(router_id)
    user_type = request.args.get('type', 'pppoe')

    try:
        api = get_router_api(router)
        if user_type == 'hotspot':
            existing = {u.get('name') for u in api.hotspot_list() if u.get('name')}
        else:
            existing = {u.get('name') for u in api.pppoe_list() if u.get('name')}

        subscribers = Subscriber.query.filter_by(
            router_id=router_id, user_type=user_type
        ).all()

        created = skipped = failed = 0
        for sub in subscribers:
            if sub.username in existing:
                skipped += 1
                continue
            try:
                api.user_create(
                    sub.username, sub.password, user_type,
                    profile=package_to_profile(sub.package)
                )
                if sub.status != 'active':
                    api.user_disable(sub.username, user_type)
                created += 1
            except MikrotikError as e:
                logger.warning(f"⚠️ {sub.username}: {e}")
                failed += 1

        flash(f'✅ المزامنة: {created} جديد، {skipped} موجود، {failed} فشل',
              'success' if failed == 0 else 'warning')
    except MikrotikError as e:
        flash(f'❌ فشل الاتصال: {e}', 'danger')

    return redirect(url_for('router_users', router_id=router_id, type=user_type))


# ============ استيراد من ملف Mikrotik .rsc ============

@app.route('/routers/<int:router_id>/import', methods=['GET', 'POST'])
def import_rsc(router_id):
    router = Router.query.get_or_404(router_id)

    if request.method == 'POST':
        file = request.files.get('rsc_file')
        push_to_router = request.form.get('push_to_router') == 'on'

        if not file or not file.filename:
            flash('❌ الرجاء اختيار ملف', 'danger')
            return redirect(url_for('import_rsc', router_id=router_id))

        if not file.filename.lower().endswith('.rsc'):
            flash('❌ الملف يجب أن يكون .rsc', 'danger')
            return redirect(url_for('import_rsc', router_id=router_id))

        try:
            content = file.read().decode('utf-8', errors='ignore')
        except Exception as e:
            flash(f'❌ فشل قراءة الملف: {e}', 'danger')
            return redirect(url_for('import_rsc', router_id=router_id))

        try:
            api = get_router_api(router)
            parsed = api.import_rsc_content(content)
        except Exception as e:
            flash(f'❌ خطأ في التحليل: {e}', 'danger')
            return redirect(url_for('import_rsc', router_id=router_id))

        all_users = []
        for u in parsed.get('pppoe', []):
            u['user_type'] = 'pppoe'
            all_users.append(u)
        for u in parsed.get('hotspot', []):
            u['user_type'] = 'hotspot'
            all_users.append(u)

        if not all_users:
            flash('⚠️ لم يتم العثور على أي مستخدمين', 'warning')
            return redirect(url_for('import_rsc', router_id=router_id))

        added = skipped = push_ok = push_fail = 0

        for u in all_users:
            username = u.get('name')
            if not username:
                continue

            if Subscriber.query.filter_by(username=username, router_id=router_id).first():
                skipped += 1
                continue

            try:
                sub = Subscriber(
                    name=username, username=username,
                    password=u.get('password', ''),
                    package=u.get('profile', ''),
                    user_type=u.get('user_type', 'pppoe'),
                    router_id=router_id,
                    status='paused' if u.get('disabled') == 'true' else 'active',
                    expires_at=None,
                )
                db.session.add(sub)
                added += 1

                if push_to_router:
                    try:
                        api.user_create(
                            username, u.get('password', ''),
                            u.get('user_type', 'pppoe'),
                            profile=u.get('profile', 'default')
                        )
                        push_ok += 1
                    except MikrotikError:
                        push_fail += 1
            except Exception as e:
                logger.error(f"⚠️ {username}: {e}")

        db.session.commit()

        msg = f'✅ تم استيراد {added} مستخدم'
        if skipped:
            msg += f' — تجاهل {skipped} (مكرر)'
        if push_to_router:
            msg += f' — رُفع {push_ok} للراوتر'
            if push_fail:
                msg += f' — فشل {push_fail}'

        flash(msg, 'success' if push_fail == 0 else 'warning')
        return redirect(url_for('subscribers'))

    return render_template('import_rsc.html', router=router)


# ============ المشتركين ============

@app.route('/subscribers')
def subscribers():
    search = request.args.get('q', '').strip()
    filter_type = request.args.get('type', '').strip()
    now = datetime.utcnow()

    try:
        expired = Subscriber.query.filter(
            Subscriber.expires_at.isnot(None),
            Subscriber.expires_at < now,
            Subscriber.status == 'active'
        ).all()
        for s in expired:
            s.status = 'expired'
        if expired:
            db.session.commit()

        query = Subscriber.query
        if search:
            query = query.filter(db.or_(
                Subscriber.username.ilike(f'%{search}%'),
                Subscriber.name.ilike(f'%{search}%')
            ))
        if filter_type in ('pppoe', 'hotspot'):
            query = query.filter_by(user_type=filter_type)

        subscribers_list = query.order_by(Subscriber.created_at.desc()).all()
    except Exception as e:
        logger.error(f"❌ {e}")
        subscribers_list = []

    routers_dict = {r.id: r for r in Router.query.all()}
    packages_list = Package.query.order_by(Package.name).all()

    return render_template(
        'subscribers.html',
        subscribers=subscribers_list,
        routers=routers_dict,
        packages=packages_list,
        search=search, now=now, filter_type=filter_type
    )


@app.route('/add-subscriber', methods=['GET', 'POST'])
@app.route('/subscribers/add', methods=['GET', 'POST'])
def add_subscriber():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        package_name = request.form.get('package', '').strip()
        router_id = request.form.get('router_id', '').strip()
        user_type = request.form.get('user_type', 'pppoe').strip()

        if user_type not in ('pppoe', 'hotspot'):
            user_type = 'pppoe'

        if not username or not password:
            flash('❌ الاسم وكلمة المرور مطلوبان', 'danger')
            return redirect(url_for('add_subscriber'))

        if Subscriber.query.filter_by(username=username).first():
            flash(f'❌ "{username}" موجود', 'danger')
            return redirect(url_for('add_subscriber'))

        try:
            expires_at = None
            pkg = None
            if package_name:
                pkg = Package.query.filter_by(name=package_name).first()
                if pkg:
                    expires_at = calculate_expiry(pkg)

            router_message = ''
            if router_id and pkg:
                router = Router.query.get(int(router_id))
                if router:
                    try:
                        api = get_router_api(router)
                        api.user_create(
                            username, password, user_type,
                            profile=package_to_profile(pkg.name)
                        )
                        router_message = ' ✅ + على الراوتر'
                    except MikrotikError as e:
                        router_message = f' ⚠️ (الراوتر: {str(e)[:40]})'

            sub = Subscriber(
                name=name or username, username=username,
                password=password, package=package_name,
                user_type=user_type,
                router_id=int(router_id) if router_id else None,
                expires_at=expires_at, status='active'
            )
            db.session.add(sub)
            db.session.commit()

            if expires_at:
                flash(f'✅ "{username}"{router_message} — ينتهي {expires_at.strftime("%Y-%m-%d")}', 'success')
            else:
                flash(f'✅ "{username}"{router_message}', 'success')
            return redirect(url_for('subscribers'))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ {str(e)}', 'danger')

    packages_list = Package.query.order_by(Package.name).all()
    routers_list = Router.query.order_by(Router.name).all()
    return render_template(
        'add_subscriber.html',
        packages=packages_list, routers=routers_list
    )


# ============ إضافة جماعية (تعمل على كل الراوترات النشطة) ============

@app.route('/subscribers/bulk-add', methods=['GET', 'POST'])
def bulk_add():
    if request.method == 'POST':
        package_name = request.form.get('package', '').strip()
        user_type = request.form.get('user_type', 'pppoe').strip()
        prefix = request.form.get('prefix', '').strip()
        char_mode = request.form.get('char_mode', 'numbers').strip()
        count = request.form.get('count', '1').strip()
        password_mode = request.form.get('password_mode', 'random')
        fixed_password = request.form.get('fixed_password', '').strip()
        password_length = request.form.get('password_length', '6').strip()
        push_to_router = request.form.get('push_to_router') == 'on'

        if user_type not in ('pppoe', 'hotspot'):
            user_type = 'pppoe'
        if char_mode not in ('numbers', 'letters', 'mixed'):
            char_mode = 'numbers'
        if password_mode not in ('random', 'same_as_username', 'fixed'):
            password_mode = 'random'

        # طول كلمة المرور
        try:
            password_length = int(password_length)
            if password_length < 4 or password_length > 20:
                password_length = 6
        except ValueError:
            password_length = 6

        # طول الاسم
        try:
            random_length = int(request.form.get('random_length', '6'))
            if random_length < 4 or random_length > 20:
                random_length = 6
        except ValueError:
            random_length = 6

        try:
            count = int(count)
        except ValueError:
            flash('❌ العدد غير صحيح', 'danger')
            return redirect(url_for('bulk_add'))

        if count < 1 or count > 500:
            flash('❌ العدد يجب أن يكون بين 1 و 500', 'danger')
            return redirect(url_for('bulk_add'))

        # ✅ جلب كل الراوترات النشطة
        active_routers = Router.query.filter_by(is_active=True).all()
        if not active_routers:
            flash('❌ لا يوجد راوترات نشطة! أضف راوتر أولًا', 'danger')
            return redirect(url_for('bulk_add'))

        pkg = Package.query.filter_by(name=package_name).first() if package_name else None
        expires_at = calculate_expiry(pkg) if pkg else None

        # الاتصال بكل راوتر
        apis = {}
        if push_to_router:
            for router in active_routers:
                try:
                    apis[router.id] = get_router_api(router)
                except Exception as e:
                    logger.warning(f"⚠️ فشل الاتصال بـ {router.name}: {e}")

        # مجموعات أحرف (بدون ملبسات)
        LETTERS = 'abcdefghijkmnpqrstuvwxyz'
        NUMS = '23456789'
        MIXED = LETTERS + NUMS

        # توليد الأسماء العشوائية
        usernames = []
        if char_mode == 'numbers':
            for _ in range(count):
                rand = ''.join(random.choices(NUMS, k=random_length))
                usernames.append(f"{prefix}{rand}")
        elif char_mode == 'letters':
            for _ in range(count):
                rand = ''.join(random.choices(LETTERS, k=random_length))
                usernames.append(f"{prefix}{rand}")
        else:
            for _ in range(count):
                rand = ''.join(random.choices(MIXED, k=random_length))
                usernames.append(f"{prefix}{rand}")

        created = failed = push_ok = push_fail = 0
        errors = []

        for username in usernames:
            # كلمة المرور
            if password_mode == 'same_as_username':
                password = username
            elif password_mode == 'fixed':
                password = fixed_password
            elif password_mode == 'random':
                password = ''.join(random.choices(MIXED, k=password_length))
            else:
                password = username

            # التحقق من التكرار
            if Subscriber.query.filter_by(username=username).first():
                errors.append(f"{username}: مكرر")
                failed += 1
                continue

            # ✅ إنشاء المستخدم على كل راوتر + حفظ سجل لكل واحد
            for router in active_routers:
                # رفع للراوتر
                if push_to_router and router.id in apis:
                    try:
                        apis[router.id].user_create(
                            username, password, user_type,
                            profile=package_to_profile(pkg.name) if pkg else 'default'
                        )
                        push_ok += 1
                    except MikrotikError as e:
                        push_fail += 1
                        errors.append(f"{username}@{router.name}: {str(e)[:30]}")

                # حفظ السجل في قاعدة البيانات
                try:
                    sub = Subscriber(
                        name=username, username=username, password=password,
                        package=package_name, user_type=user_type,
                        router_id=router.id,
                        expires_at=expires_at, status='active'
                    )
                    db.session.add(sub)
                    created += 1
                except Exception as e:
                    failed += 1
                    errors.append(f"{username}@{router.name}: {str(e)[:30]}")

        db.session.commit()

        msg = f'✅ تم إنشاء {created} سجل على {len(active_routers)} راوتر'
        if failed:
            msg += f' — فشل {failed}'
        if push_to_router:
            msg += f' — رُفع {push_ok}'
            if push_fail:
                msg += f' — فشل رفع {push_fail}'

        flash(msg, 'success' if failed == 0 else 'warning')
        if errors:
            for err in errors[:5]:
                flash(f'⚠️ {err}', 'warning')

        return redirect(url_for('subscribers'))

    # GET
    packages_list = Package.query.order_by(Package.name).all()
    active_routers = Router.query.filter_by(is_active=True).all()
    return render_template(
        'bulk_add.html',
        packages=packages_list,
        active_routers=active_routers
    )


# ============ تعديل/حذف/تشغيل المشتركين ============

@app.route('/subscribers/toggle/<int:sub_id>')
def toggle_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        router_msg = ''
        ut = sub.user_type or 'pppoe'

        if sub.status == 'active':
            sub.status = 'paused'
            if sub.router_id:
                router = Router.query.get(sub.router_id)
                if router:
                    try:
                        api = get_router_api(router)
                        api.user_disable(sub.username, ut)
                        api.user_kick(sub.username, ut)
                        router_msg = ' وتم إيقافه على الراوتر'
                    except MikrotikError as e:
                        router_msg = f' (راوتر: {str(e)[:30]})'
            flash(f'⏸ تم إيقاف "{sub.username}"{router_msg}', 'warning')
        else:
            if sub.expires_at and sub.expires_at < datetime.utcnow():
                flash('⚠️ الاشتراك منتهي', 'danger')
            else:
                sub.status = 'active'
                if sub.router_id:
                    router = Router.query.get(sub.router_id)
                    if router:
                        try:
                            api = get_router_api(router)
                            api.user_enable(sub.username, ut)
                            router_msg = ' وتم تفعيله على الراوتر'
                        except MikrotikError as e:
                            router_msg = f' (راوتر: {str(e)[:30]})'
                flash(f'▶ تم تفعيل "{sub.username}"{router_msg}', 'success')
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


@app.route('/subscribers/reset/<int:sub_id>')
def reset_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)

        if not sub.package:
            flash('⚠️ بلا باقة', 'danger')
            return redirect(url_for('subscribers'))

        pkg = Package.query.filter_by(name=sub.package).first()
        if not pkg:
            flash('⚠️ الباقة غير موجودة', 'danger')
            return redirect(url_for('subscribers'))

        sub.expires_at = calculate_expiry(pkg)
        sub.status = 'active'
        router_msg = ''
        ut = sub.user_type or 'pppoe'

        if sub.router_id:
            router = Router.query.get(sub.router_id)
            if router:
                try:
                    api = get_router_api(router)
                    api.user_enable(sub.username, ut)
                    api.user_kick(sub.username, ut)
                    router_msg = ' + على الراوتر'
                except MikrotikError as e:
                    router_msg = f' (راوتر: {str(e)[:30]})'

        db.session.commit()
        flash(f'🔄 تم التصفير{router_msg} — ينتهي {sub.expires_at.strftime("%Y-%m-%d")}', 'success')
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

        if pkg:
            sub.expires_at = calculate_expiry(pkg, base)
        else:
            sub.expires_at = base + timedelta(days=30)

        sub.status = 'active'
        db.session.commit()
        flash(f'➕ تم التمديد — ينتهي {sub.expires_at.strftime("%Y-%m-%d")}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


@app.route('/subscribers/update/<int:sub_id>', methods=['POST'])
def update_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        old_password = sub.password
        old_package = sub.package
        old_username = sub.username

        sub.name = request.form.get('name', '').strip() or sub.name
        new_username = request.form.get('username', '').strip()
        if new_username:
            sub.username = new_username
        password = request.form.get('password', '').strip()
        if password:
            sub.password = password

        package_name = request.form.get('package', '').strip()
        if package_name and package_name != sub.package:
            sub.package = package_name
            pkg = Package.query.filter_by(name=package_name).first()
            if pkg:
                sub.expires_at = calculate_expiry(pkg)

        router_id = request.form.get('router_id', '').strip()
        sub.router_id = int(router_id) if router_id else None

        ut = sub.user_type or 'pppoe'
        router_msg = ''

        if sub.router_id:
            router = Router.query.get(sub.router_id)
            if router:
                try:
                    api = get_router_api(router)
                    if password and password != old_password:
                        api.user_update_password(sub.username, password, ut)
                    if package_name and package_name != old_package:
                        api.user_update_profile(sub.username, package_to_profile(package_name), ut)
                        api.user_kick(sub.username, ut)
                    if new_username and new_username != old_username:
                        api.user_delete(old_username, ut)
                        pkg = Package.query.filter_by(name=package_name or old_package).first()
                        profile_name = package_to_profile(pkg.name) if pkg else 'default'
                        api.user_create(new_username, password or old_password, ut, profile=profile_name)
                    router_msg = ' ✅ + الراوتر'
                except MikrotikError as e:
                    router_msg = f' ⚠️ ({str(e)[:40]})'

        db.session.commit()
        flash(f'✅ تم التحديث{router_msg}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


@app.route('/subscribers/delete/<int:sub_id>')
def delete_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        router_msg = ''
        ut = sub.user_type or 'pppoe'

        if sub.router_id:
            router = Router.query.get(sub.router_id)
            if router:
                try:
                    api = get_router_api(router)
                    api.user_kick(sub.username, ut)
                    api.user_delete(sub.username, ut)
                    router_msg = ' + من الراوتر'
                except MikrotikError as e:
                    router_msg = f' (راوتر: {str(e)[:30]})'

        db.session.delete(sub)
        db.session.commit()
        flash(f'✅ تم الحذف{router_msg}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


# ============ تصدير المشتركين ============

@app.route('/subscribers/export/<format>')
def export_subscribers(format):
    filter_type = request.args.get('type', '').strip()
    ids_param = request.args.get('ids', '').strip()

    if ids_param:
        try:
            ids_list = [int(x) for x in ids_param.split(',') if x.strip().isdigit()]
            subs = Subscriber.query.filter(Subscriber.id.in_(ids_list))\
                                   .order_by(Subscriber.created_at.desc()).all()
        except Exception as e:
            logger.error(f"❌ ids parsing: {e}")
            subs = []
    else:
        query = Subscriber.query
        if filter_type in ('pppoe', 'hotspot'):
            query = query.filter_by(user_type=filter_type)
        subs = query.order_by(Subscriber.created_at.desc()).all()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if format == 'csv':
        output = io.StringIO()
        output.write('\ufeff')
        writer = csv.writer(output)
        writer.writerow(['#', 'الاسم', 'اسم المستخدم', 'كلمة المرور',
                         'الباقة', 'النوع', 'الحالة', 'الانتهاء'])
        for i, s in enumerate(subs, 1):
            writer.writerow([
                i, s.name or '', s.username, s.password,
                s.package or '', s.user_type or 'pppoe', s.status,
                s.expires_at.strftime('%Y-%m-%d') if s.expires_at else ''
            ])
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'subscribers_{timestamp}.csv'
        )

    elif format == 'txt':
        lines = []
        lines.append('=' * 60)
        lines.append('  ZINAR — قائمة المشتركين')
        lines.append(f'  {datetime.now().strftime("%Y-%m-%d %H:%M")}')
        lines.append(f'  العدد: {len(subs)}')
        lines.append('=' * 60)
        lines.append('')
        for i, s in enumerate(subs, 1):
            lines.append(f'{i}. {s.name or s.username}')
            lines.append(f'   Username: {s.username}')
            lines.append(f'   Password: {s.password}')
            lines.append(f'   Package : {s.package or "-"}')
            lines.append(f'   Type    : {s.user_type or "pppoe"}')
            lines.append(f'   Status  : {s.status}')
            if s.expires_at:
                lines.append(f'   Expires : {s.expires_at.strftime("%Y-%m-%d")}')
            lines.append('-' * 60)

        content = '\n'.join(lines)
        return send_file(
            io.BytesIO(content.encode('utf-8')),
            mimetype='text/plain',
            as_attachment=True,
            download_name=f'subscribers_{timestamp}.txt'
        )

    elif format == 'print':
        return render_template('print_subscribers.html',
                               subscribers=subs,
                               now=datetime.utcnow(),
                               filter_type=filter_type)

    flash('❌ صيغة غير مدعومة', 'danger')
    return redirect(url_for('subscribers'))


# ============ الباقات ============

@app.route('/packages')
def packages():
    packages_list = Package.query.order_by(Package.id).all()
    return render_template('packages.html', packages=packages_list)


@app.route('/packages/add', methods=['POST'])
def add_package():
    name = request.form.get('name', '').strip()
    speed = request.form.get('speed', '').strip()
    price = request.form.get('price', '0').strip()
    duration = request.form.get('duration', '1').strip()
    duration_unit = request.form.get('duration_unit', 'days').strip()
    user_type = request.form.get('user_type', 'pppoe').strip()

    if duration_unit not in ('days', 'months'):
        duration_unit = 'days'
    if user_type not in ('pppoe', 'hotspot'):
        user_type = 'pppoe'

    if not name:
        flash('❌ اسم الباقة مطلوب', 'danger')
        return redirect(url_for('packages'))

    if Package.query.filter_by(name=name).first():
        flash('❌ الاسم موجود', 'danger')
        return redirect(url_for('packages'))

    try:
        pkg = Package(
            name=name, speed=speed, price=float(price or 0),
            duration=int(duration or 1),
            duration_unit=duration_unit, user_type=user_type
        )
        db.session.add(pkg)
        db.session.commit()
        unit = 'شهر' if duration_unit == 'months' else 'يوم'
        flash(f'✅ تم إضافة "{name}" — {duration} {unit}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('packages'))


@app.route('/packages/update/<int:pkg_id>', methods=['POST'])
def update_package(pkg_id):
    try:
        pkg = Package.query.get_or_404(pkg_id)
        name = request.form.get('name', '').strip()
        speed = request.form.get('speed', '').strip()
        price = request.form.get('price', '0').strip()
        duration = request.form.get('duration', '1').strip()
        duration_unit = request.form.get('duration_unit', 'days').strip()
        user_type = request.form.get('user_type', 'pppoe').strip()

        if duration_unit not in ('days', 'months'):
            duration_unit = 'days'
        if user_type not in ('pppoe', 'hotspot'):
            user_type = 'pppoe'

        if not name:
            flash('❌ الاسم مطلوب', 'danger')
            return redirect(url_for('packages'))

        if Package.query.filter(Package.name == name, Package.id != pkg_id).first():
            flash('❌ الاسم موجود', 'danger')
            return redirect(url_for('packages'))

        pkg.name = name
        pkg.speed = speed
        pkg.price = float(price or 0)
        pkg.duration = int(duration or 1)
        pkg.duration_unit = duration_unit
        pkg.user_type = user_type
        db.session.commit()
        flash(f'✅ تم التحديث', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('packages'))


@app.route('/packages/delete/<int:pkg_id>')
def delete_package(pkg_id):
    try:
        pkg = Package.query.get_or_404(pkg_id)
        db.session.delete(pkg)
        db.session.commit()
        flash('✅ تم الحذف', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('packages'))


# ============ الدفعات ============

@app.route('/payments')
def payments():
    payments_list = Payment.query.order_by(Payment.created_at.desc()).all()
    return render_template('payments.html', payments=payments_list)


@app.route('/payments/<int:payment_id>/complete', methods=['POST'])
def complete_payment(payment_id):
    try:
        payment = Payment.query.get_or_404(payment_id)
        payment.status = 'completed'
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============ معالجات الأخطاء ============

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', error='الصفحة غير موجودة'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', error='خطأ داخلي'), 500


# ============ نقطة التشغيل ============

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
