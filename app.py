# app.py
import os
import logging
import traceback
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
    # Render قد يعطي postgres:// — نحوّلها إلى postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    # ✅ استخدام psycopg3 بدل psycopg2
    if 'postgresql://' in database_url and '+psycopg' not in database_url:
        database_url = database_url.replace('postgresql://', 'postgresql+psycopg://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ============ نماذج قاعدة البيانات ============

class Router(db.Model):
    __tablename__ = 'routers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    ip_address = db.Column(db.String(50), nullable=False)
    username = db.Column(db.String(50), nullable=False)
    password = db.Column(db.String(150), nullable=False)
    port = db.Column(db.Integer, default=22)          # ✅ SSH افتراضي
    is_master = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AdminUser(db.Model):
    __tablename__ = 'admin_users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)   # ✅ يكفي للهاش
    email = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Subscriber(db.Model):
    __tablename__ = 'subscribers'
    id = db.Column(db.Integer, primary_key=True)
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
    status = db.Column(db.String(20), default='pending')  # pending/completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ============ تهيئة قاعدة البيانات ============
def init_database():
    """تُستدعى مرة واحدة عند بدء التطبيق."""
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


init_database()


# ============ دوال مساعدة ============

def test_mikrotik_connection(router):
    """اختبار الاتصال بـ Mikrotik عبر SSH."""
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
    """جلب الراوتر الرئيسي."""
    try:
        return Router.query.filter_by(is_master=True).first()
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        return None


def _day_bounds(day=None):
    """حدود اليوم (بداية/نهاية) — تعمل مع SQLite و PostgreSQL."""
    if day is None:
        day = datetime.utcnow()
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


def login_required(f):
    """Decorator لحماية المسارات."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('admin_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


# ============ المسارات (Routes) ============

@app.before_request
def check_admin_login():
    """التحقق من تسجيل الدخول — حماية شاملة."""
    if request.endpoint is None:
        return
    if request.endpoint.startswith('static'):
        return
    public_endpoints = {'login', 'logout'}
    if request.endpoint in public_endpoints:
        return
    if not session.get('admin_id'):
        return redirect(url_for('login'))


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


@app.route('/dashboard')
def dashboard():
    try:
        routers_list = Router.query.all()
        routers_count = len(routers_list)
        routers_online = sum(1 for r in routers_list if test_mikrotik_connection(r))

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


# ============ إدارة الراوترات ============

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


# ============ إدارة المشتركين ============

@app.route('/subscribers')
def subscribers():
    search = request.args.get('q', '').strip()
    try:
        query = Subscriber.query
        if search:
            query = query.filter(Subscriber.username.ilike(f'%{search}%'))
        subscribers_list = query.all()
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        subscribers_list = []

    return render_template(
        'subscribers.html',
        subscribers=subscribers_list,
        search=search
    )


@app.route('/add-subscriber', methods=['GET', 'POST'])
@app.route('/subscribers/add', methods=['GET', 'POST'])
def add_subscriber():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        package = request.form.get('package', '').strip()

        if not username or not password:
            flash('❌ الاسم وكلمة المرور مطلوبان', 'danger')
            return redirect(url_for('add_subscriber'))

        try:
            sub = Subscriber(
                username=username,
                password=password,
                package=package
            )
            db.session.add(sub)
            db.session.commit()
            flash(f'✅ تم إضافة "{username}" بنجاح', 'success')
            return redirect(url_for('subscribers'))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')

    return render_template('add_subscriber.html')


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


# ============ إدارة الباقات ============

PACKAGES = [
    {'id': 1, 'name': 'باقة 5 ميجا',  'speed': '5M/5M',   'price': 15000, 'duration': 'شهر'},
    {'id': 2, 'name': 'باقة 10 ميجا', 'speed': '10M/10M', 'price': 25000, 'duration': 'شهر'},
    {'id': 3, 'name': 'باقة 20 ميجا', 'speed': '20M/20M', 'price': 40000, 'duration': 'شهر'},
    {'id': 4, 'name': 'باقة 50 ميجا', 'speed': '50M/50M', 'price': 80000, 'duration': 'شهر'},
]


@app.route('/packages')
def packages():
    return render_template('packages.html', packages=PACKAGES)


# ============ إدارة الدفعات ============

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


# ============ إدارة حساب المدير ============

@app.route('/admin/profile', methods=['POST'])
def update_admin_profile():
    """API لتحديث بيانات Admin."""
    admin_id = session.get('admin_id')
    if not admin_id:
        return jsonify({'ok': False, 'error': 'غير مصرح'}), 401

    admin = AdminUser.query.get(admin_id)
    if not admin:
        return jsonify({'ok': False, 'error': 'المستخدم غير موجود'}), 404

    try:
        data = request.get_json(silent=True) or request.form

        new_username = (data.get('username') or '').strip()
        new_email = (data.get('email') or '').strip()
        new_password = (data.get('password') or '').strip()
        old_password = (data.get('old_password') or '').strip()

        if new_password:
            if not old_password or not check_password_hash(admin.password, old_password):
                return jsonify({'ok': False, 'error': 'كلمة المرور القديمة غير صحيحة'}), 400
            admin.password = generate_password_hash(new_password)

        if new_username and new_username != admin.username:
            if AdminUser.query.filter_by(username=new_username).first():
                return jsonify({'ok': False, 'error': 'اسم المستخدم مستخدم مسبقاً'}), 400
            admin.username = new_username
            session['admin_name'] = new_username

        if new_email:
            admin.email = new_email

        db.session.commit()
        return jsonify({'ok': True, 'message': 'تم تحديث البيانات بنجاح'})

    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ خطأ في update_admin_profile: {e}")
        logger.error(traceback.format_exc())
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
