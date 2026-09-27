import os
import logging
import traceback
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import paramiko
import socket

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
        database_url = database_url.replace('postgresql://', 'postgresql+psycopg2://', 1)

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
    port = db.Column(db.Integer, default=8728)
    is_master = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AdminUser(db.Model):
    __tablename__ = 'admin_users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
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

# إنشاء الجداول
with app.app_context():
    try:
        db.create_all()
        # إنشاء admin افتراضي
        if not AdminUser.query.filter_by(username='admin').first():
            admin = AdminUser(username='admin', password='admin123', email='admin@zinar.com')
            db.session.add(admin)
            db.session.commit()
        logger.info("✅ تم تهيئة قاعدة البيانات")
    except Exception as e:
        logger.error(f"❌ خطأ في قاعدة البيانات: {e}")

# ============ دوال مساعدة ============

def test_mikrotik_connection(router):
    """اختبار الاتصال بـ Mikrotik"""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            router.ip_address,
            port=router.port,
            username=router.username,
            password=router.password,
            timeout=5
        )
        ssh.close()
        return True
    except Exception as e:
        logger.warning(f"⚠️ فشل الاتصال بـ {router.name}: {str(e)}")
        return False

def get_master_router():
    """جلب الراوتر الرئيسي"""
    try:
        return Router.query.filter_by(is_master=True).first()
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        return None

# ============ المسارات (Routes) ============

@app.before_request
def check_admin_login():
    """التحقق من تسجيل الدخول"""
    if request.endpoint and request.endpoint.startswith('static'):
        return
    if request.endpoint not in ['login', 'index']:
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
        if admin and admin.password == password:
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
        # جلب الإحصائيات
        routers_list = Router.query.all()
        routers_count = len(routers_list)
        routers_online = sum(1 for r in routers_list if test_mikrotik_connection(r))
        
        master = get_master_router()
        sub_count = Subscriber.query.count()
        active_subs = Subscriber.query.filter_by(status='active').count()
        pending_pays = Payment.query.filter_by(status='pending').count()
        
        # حساب الإيرادات اليوم
        today_date = datetime.utcnow().date()
        today_revenue = db.session.query(db.func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            db.func.date(Payment.created_at) == today_date
        ).scalar() or 0
        
        # المستخدمين الجدد اليوم
        new_users_today = Subscriber.query.filter(
            db.func.date(Subscriber.created_at) == today_date
        ).count()
        
        # آخر المشتركين
        subscribers_preview = Subscriber.query.order_by(Subscriber.created_at.desc()).limit(8).all()

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
            admin_name=session.get('admin_name', 'مدير')
        )
    except Exception as e:
        logger.error(f"❌ خطأ في dashboard: {e}")
        logger.error(traceback.format_exc())
        flash(f'❌ خطأ: {str(e)}', 'danger')
        return render_template('error.html', error=str(e)), 500

@app.route('/routers', methods=['GET', 'POST'])
def routers():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        ip_address = request.form.get('ip_address', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        port = request.form.get('port', '8728').strip()
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
            port = 8728

        try:
            if is_master:
                Router.query.update({Router.is_master: False})
            
            new_router = Router(
                name=name,
                ip_address=ip_address,
                username=username,
                password=password,
                port=port,
                is_master=is_master
            )
            
            db.session.add(new_router)
            db.session.commit()
            
            if test_mikrotik_connection(new_router):
                flash(f'✅ تمت إضافة الراوتر "{name}" والاتصال ناجح', 'success')
            else:
                flash(f'⚠️ تمت الإضافة لكن الاتصال فشل', 'warning')
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
        Router.query.update({Router.is_master: False})
        router = Router.query.get_or_404(router_id)
        router.is_master = True
        db.session.commit()
        flash(f'✅ تم تحديث الراوتر الرئيسي', 'success')
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

    return render_template('subscribers.html', subscribers=subscribers_list, search=search)

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
            sub = Subscriber(username=username, password=password, package=package)
            db.session.add(sub)
            db.session.commit()
            flash(f'✅ تم إضافة "{username}" بنجاح', 'success')
            return redirect(url_for('subscribers'))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ خطأ: {str(e)}', 'danger')

    return render_template('add_subscriber.html')

@app.route('/admin/profile', methods=['POST'])
def update_admin_profile():
    """API لتحديث بيانات Admin
