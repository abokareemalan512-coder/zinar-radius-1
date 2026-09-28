# app.py
import os
import logging
import traceback
import calendar
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, session
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import paramiko
import socket

# ============ الإعدادات الأساسية ============
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'zinar-secret-key-2024')

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
    duration = db.Column(db.Integer, default=30)               # الرقم
    duration_unit = db.Column(db.String(10), default='days')    # 'days' أو 'months'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============ دوال مساعدة ============

def add_months(source_date, months):
    """إضافة أشهر بشكل صحيح — يحترم عدد أيام كل شهر"""
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(source_date.day, last_day)
    return source_date.replace(year=year, month=month, day=day)


def calculate_expiry(pkg, start_date=None):
    """حساب تاريخ الانتهاء حسب نوع المدة (أيام أو أشهر)"""
    if start_date is None:
        start_date = datetime.utcnow()
    if not pkg or not pkg.duration:
        return None
    if pkg.duration_unit == 'months':
        return add_months(start_date, pkg.duration)
    return start_date + timedelta(days=pkg.duration)


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
    """إضافة الأعمدة الناقصة للجداول الموجودة (Auto Migration)."""
    with app.app_context():
        try:
            from sqlalchemy import text, inspect
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()

            with db.engine.connect() as conn:
                # routers.is_active
                if 'routers' in existing_tables:
                    cols = [c['name'] for c in inspector.get_columns('routers')]
                    if 'is_active' not in cols:
                        conn.execute(text(
                            "ALTER TABLE routers ADD COLUMN is_active BOOLEAN DEFAULT TRUE"
                        ))
                        logger.info("✅ تم إضافة routers.is_active")

                # subscribers.name
                if 'subscribers' in existing_tables:
                    cols = [c['name'] for c in inspector.get_columns('subscribers')]
                    if 'name' not in cols:
                        conn.execute(text(
                            "ALTER TABLE subscribers ADD COLUMN name VARCHAR(100)"
                        ))
                        logger.info("✅ تم إضافة subscribers.name")

                # packages.duration_unit
                if 'packages' in existing_tables:
                    cols = [c['name'] for c in inspector.get_columns('packages')]
                    if 'duration_unit' not in cols:
                        conn.execute(text(
                            "ALTER TABLE packages ADD COLUMN duration_unit VARCHAR(10) DEFAULT 'days'"
                        ))
                        logger.info("✅ تم إضافة packages.duration_unit")

                conn.commit()
            logger.info("✅ فحص الأعمدة اكتمل")
        except Exception as e:
            logger.warning(f"⚠️ تحذير في ensure_columns: {e}")


init_database()
ensure_columns()


def test_mikrotik_connection(router):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=router.ip_address,
            port=router.port or 22,
            username=router.username,
            password=router.password,
            timeout=5,
            allow_agent=False,
            look_for_keys=False,
        )
        ssh.close()
        return True
    except Exception as e:
        logger.warning(f"⚠️ فشل الاتصال بـ {router.name}: {e}")
        return False


def get_master_router():
    try:
        return Router.query.filter_by(is_master=True).first()
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
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
            flash('❌ الرجاء إدخال اسم المستخدم وكلمة المرور', 'danger')
            return redirect(url_for('login'))

        admin = AdminUser.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password, password):
            session['admin_id'] = admin.id
            session['admin_name'] = admin.username
            flash('✅ تم تسجيل الدخول بنجاح', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('❌ بيانات الدخول غير صحيحة', 'danger')

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
        routers_online = sum(
            1 for r in routers_list
            if r.is_active and test_mikrotik_connection(r)
        )

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

        subscribers_preview = (
            Subscriber.query
            .order_by(Subscriber.created_at.desc())
            .limit(8)
            .all()
        )

        return render_template(
            'dashboard.html',
            routers_count=routers_count,
            routers_online=routers_online,
            sub_count=sub_count,
            active_subs=active_subs,
            active_sessions=active_subs,
            today_revenue=today_revenue,
            active_vouchers=0,
            new_users_today=new_users_today,
            pending_pays=pending_pays,
            subscribers=subscribers_preview,
            has_master=master is not None,
            admin_name=session.get('admin_name', 'مدير'),
        )
    except Exception as e:
        logger.error(f"❌ خطأ في dashboard: {e}")
        logger.error(traceback.format_exc())
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

        if not current_password:
            flash('❌ يجب إدخال كلمة المرور الحالية', 'danger')
            return redirect(url_for('dashboard'))

        if not check_password_hash(admin.password, current_password):
            flash('❌ كلمة المرور الحالية غير صحيحة', 'danger')
            return redirect(url_for('dashboard'))

        if new_username and new_username != admin.username:
            existing = AdminUser.query.filter(
                AdminUser.username == new_username,
                AdminUser.id != admin_id
            ).first()
            if existing:
                flash('❌ اسم المستخدم موجود مسبقاً', 'danger')
                return redirect(url_for('dashboard'))
            admin.username = new_username
            session['admin_name'] = new_username

        if new_password:
            if new_password != confirm_password:
                flash('❌ كلمتا المرور الجديدتان غير متطابقتين', 'danger')
                return redirect(url_for('dashboard'))
            if len(new_password) < 6:
                flash('❌ كلمة المرور يجب أن تكون 6 أحرف على الأقل', 'danger')
                return redirect(url_for('dashboard'))
            admin.password = generate_password_hash(new_password)

        db.session.commit()
        flash('✅ تم تحديث بيانات الدخول بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ خطأ في change_admin_credentials: {e}")
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
            flash('❌ الاسم وعنوان IP مطلوبان', 'danger')
            return redirect(url_for('routers'))

        if Router.query.filter_by(name=name).first():
            flash('❌ اسم الراوتر موجود مسبقاً', 'danger')
            return redirect(url_for('routers'))

        try:
            port = int(port)
        except ValueError:
            port = 22

        try:
            if is_master:
                Router.query.update(
                    {Router.is_master: False},
                    synchronize_session=False
                )

            new_router = Router(
                name=name,
                ip_address=ip_address,
                username=username,
                password=password,
                port=port,
                is_master=is_master,
                is_active=True
            )

            db.session.add(new_router)
            db.session.commit()

            if test_mikrotik_connection(new_router):
                flash(f'✅ تمت إضافة الراوتر "{name}" والاتصال ناجح', 'success')
            else:
                flash('⚠️ تمت الإضافة لكن الاتصال فشل', 'warning')
        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ خطأ: {e}")
            flash(f'❌ خطأ: {str(e)}', 'danger')

        return redirect(url_for('routers'))

    try:
        routers_list = Router.query.all()
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        routers_list = []

    return render_template('routers.html', routers=routers_list)


@app.route('/routers/set_master/<int:router_id>')
def set_master_router(router_id):
    try:
        Router.query.update(
            {Router.is_master: False},
            synchronize_session=False
        )
        router = Router.query.get_or_404(router_id)
        router.is_master = True
        db.session.commit()
        flash('✅ تم تحديث الراوتر الرئيسي', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('routers'))


@app.route('/routers/toggle/<int:router_id>')
def toggle_router(router_id):
    try:
        router = Router.query.get_or_404(router_id)
        router.is_active = not router.is_active
        db.session.commit()
        state = "تشغيل" if router.is_active else "إيقاف"
        flash(f'✅ تم {state} الراوتر "{router.name}"', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
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
            flash('❌ الاسم وعنوان IP مطلوبان', 'danger')
            return redirect(url_for('routers'))

        existing = Router.query.filter(
            Router.name == name,
            Router.id != router_id
        ).first()
        if existing:
            flash('❌ اسم الراوتر موجود مسبقاً', 'danger')
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
        flash(f'✅ تم تحديث الراوتر "{name}" بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ خطأ في update_router: {e}")
        flash(f'❌ خطأ: {str(e)}', 'danger')

    return redirect(url_for('routers'))


@app.route('/routers/test/<int:router_id>')
def test_router(router_id):
    try:
        router = Router.query.get_or_404(router_id)
        if test_mikrotik_connection(router):
            flash(f'✅ الاتصال بالراوتر "{router.name}" ناجح', 'success')
        else:
            flash(f'⚠️ فشل الاتصال بالراوتر "{router.name}"', 'warning')
    except Exception as e:
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('routers'))


@app.route('/routers/delete/<int:router_id>')
def delete_router(router_id):
    try:
        router = Router.query.get_or_404(router_id)
        db.session.delete(router)
        db.session.commit()
        flash('✅ تم الحذف بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('routers'))


# ============ المشتركين ============

@app.route('/subscribers')
def subscribers():
    search = request.args.get('q', '').strip()
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
            query = query.filter(
                db.or_(
                    Subscriber.username.ilike(f'%{search}%'),
                    Subscriber.name.ilike(f'%{search}%')
                )
            )
        subscribers_list = query.order_by(Subscriber.created_at.desc()).all()
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        subscribers_list = []

    routers_dict = {r.id: r for r in Router.query.all()}
    packages_list = Package.query.order_by(Package.name).all()

    return render_template(
        'subscribers.html',
        subscribers=subscribers_list,
        routers=routers_dict,
        packages=packages_list,
        search=search,
        now=now
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

        if not username or not password:
            flash('❌ اسم المستخدم وكلمة المرور مطلوبان', 'danger')
            return redirect(url_for('add_subscriber'))

        try:
            expires_at = None
            if package_name:
                pkg = Package.query.filter_by(name=package_name).first()
                if pkg:
                    expires_at = calculate_expiry(pkg)

            sub = Subscriber(
                name=name or username,
                username=username,
                password=password,
                package=package_name,
                router_id=int(router_id) if router_id else None,
                expires_at=expires_at,
                status='active'
            )
            db.session.add(sub)
            db.session.commit()

            if expires_at:
                flash(f'✅ تم إضافة "{username}" — ينتهي في {expires_at.strftime("%Y-%m-%d")}', 'success')
            else:
                flash(f'✅ تم إضافة "{username}" بنجاح', 'success')
            return redirect(url_for('subscribers'))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')

    packages_list = Package.query.order_by(Package.name).all()
    routers_list = Router.query.order_by(Router.name).all()
    return render_template(
        'add_subscriber.html',
        packages=packages_list,
        routers=routers_list
    )


@app.route('/subscribers/toggle/<int:sub_id>')
def toggle_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        if sub.status == 'active':
            sub.status = 'paused'
            flash(f'⏸ تم إيقاف "{sub.username}"', 'warning')
        else:
            if sub.expires_at and sub.expires_at < datetime.utcnow():
                flash(f'⚠️ لا يمكن التفعيل — اشتراك "{sub.username}" منتهي', 'danger')
            else:
                sub.status = 'active'
                flash(f'▶ تم تفعيل "{sub.username}"', 'success')
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


@app.route('/subscribers/reset/<int:sub_id>')
def reset_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)

        if not sub.package:
            flash(f'⚠️ لا يمكن التصفير — "{sub.username}" بلا باقة', 'danger')
            return redirect(url_for('subscribers'))

        pkg = Package.query.filter_by(name=sub.package).first()
        if not pkg:
            flash(f'⚠️ لا يمكن التصفير — الباقة "{sub.package}" غير موجودة', 'danger')
            return redirect(url_for('subscribers'))

        sub.expires_at = calculate_expiry(pkg)
        sub.status = 'active'
        db.session.commit()

        flash(f'🔄 تم تصفير باقة "{sub.username}" — ينتهي في {sub.expires_at.strftime("%Y-%m-%d")}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


@app.route('/subscribers/extend/<int:sub_id>')
def extend_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)

        # التمديد حسب نوع الباقة
        pkg = Package.query.filter_by(name=sub.package).first() if sub.package else None
        if pkg:
            base = sub.expires_at if sub.expires_at and sub.expires_at > datetime.utcnow() else datetime.utcnow()
            sub.expires_at = calculate_expiry(pkg, base)
        else:
            base = sub.expires_at if sub.expires_at and sub.expires_at > datetime.utcnow() else datetime.utcnow()
            sub.expires_at = base + timedelta(days=30)

        sub.status = 'active'
        db.session.commit()

        flash(f'➕ تم تمديد "{sub.username}" — ينتهي في {sub.expires_at.strftime("%Y-%m-%d")}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


@app.route('/subscribers/update/<int:sub_id>', methods=['POST'])
def update_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)

        sub.name = request.form.get('name', '').strip() or sub.name
        sub.username = request.form.get('username', '').strip() or sub.username

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

        db.session.commit()
        flash(f'✅ تم تحديث بيانات "{sub.username}"', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


@app.route('/subscribers/delete/<int:sub_id>')
def delete_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        db.session.delete(sub)
        db.session.commit()
        flash('✅ تم حذف المشترك', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


# ============ الباقات ============

@app.route('/packages')
def packages():
    try:
        packages_list = Package.query.order_by(Package.id).all()
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        packages_list = []
    return render_template('packages.html', packages=packages_list)


@app.route('/packages/add', methods=['POST'])
def add_package():
    name = request.form.get('name', '').strip()
    speed = request.form.get('speed', '').strip()
    price = request.form.get('price', '0').strip()
    duration = request.form.get('duration', '1').strip()
    duration_unit = request.form.get('duration_unit', 'days').strip()

    if duration_unit not in ('days', 'months'):
        duration_unit = 'days'

    if not name:
        flash('❌ اسم الباقة مطلوب', 'danger')
        return redirect(url_for('packages'))

    if Package.query.filter_by(name=name).first():
        flash('❌ اسم الباقة موجود مسبقاً', 'danger')
        return redirect(url_for('packages'))

    try:
        pkg = Package(
            name=name,
            speed=speed,
            price=float(price or 0),
            duration=int(duration or 1),
            duration_unit=duration_unit,
        )
        db.session.add(pkg)
        db.session.commit()
        unit = 'شهر' if duration_unit == 'months' else 'يوم'
        flash(f'✅ تم إضافة باقة "{name}" — {duration} {unit}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')

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

        if duration_unit not in ('days', 'months'):
            duration_unit = 'days'

        if not name:
            flash('❌ اسم الباقة مطلوب', 'danger')
            return redirect(url_for('packages'))

        existing = Package.query.filter(
            Package.name == name,
            Package.id != pkg_id
        ).first()
        if existing:
            flash('❌ اسم الباقة موجود مسبقاً', 'danger')
            return redirect(url_for('packages'))

        pkg.name = name
        pkg.speed = speed
        pkg.price = float(price or 0)
        pkg.duration = int(duration or 1)
        pkg.duration_unit = duration_unit

        db.session.commit()
        flash(f'✅ تم تحديث باقة "{name}"', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')

    return redirect(url_for('packages'))


@app.route('/packages/delete/<int:pkg_id>')
def delete_package(pkg_id):
    try:
        pkg = Package.query.get_or_404(pkg_id)
        db.session.delete(pkg)
        db.session.commit()
        flash('✅ تم حذف الباقة', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('packages'))


# ============ الدفعات ============

@app.route('/payments')
def payments():
    try:
        payments_list = (
            Payment.query
            .order_by(Payment.created_at.desc())
            .all()
        )
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        payments_list = []
    return render_template('payments.html', payments=payments_list)


@app.route('/payments/<int:payment_id>/complete', methods=['POST'])
def complete_payment(payment_id):
    try:
        payment = Payment.query.get_or_404(payment_id)
        payment.status = 'completed'
        db.session.commit()
        return jsonify({'ok': True, 'message': 'تم تأكيد الدفعة'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============ معالجات الأخطاء ============

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', error='الصفحة غير موجودة'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', error='خطأ داخلي في السيرفر'), 500


# ============ نقطة التشغيل ============

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
