import os
import logging
import traceback
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import librouteros

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'zinar-secret-key-2024')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ إعدادات Database ============
database_url = os.environ.get('DATABASE_URL')
if not database_url:
    database_url = 'sqlite:///zinar.db'
else:
    # تحويل postgres إلى postgresql
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    if 'postgresql://' in database_url and '+psycopg' not in database_url:
        database_url = database_url.replace('postgresql://', 'postgresql+psycopg2://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 3600,
}

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
    status = db.Column(db.String(20), default='offline')  # online/offline
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Router {self.name}>'

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
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    package = db.Column(db.String(100))
    router_id = db.Column(db.Integer, db.ForeignKey('routers.id'))
    status = db.Column(db.String(20), default='active')  # active/inactive
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)

class Session(db.Model):
    __tablename__ = 'sessions'
    id = db.Column(db.Integer, primary_key=True)
    subscriber_id = db.Column(db.Integer, db.ForeignKey('subscribers.id'))
    router_id = db.Column(db.Integer, db.ForeignKey('routers.id'))
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime)
    upload = db.Column(db.Integer, default=0)
    download = db.Column(db.Integer, default=0)

# إنشاء الجداول
with app.app_context():
    try:
        db.create_all()
        logger.info("✅ تم إنشاء قاعدة البيانات بنجاح")
    except Exception as e:
        logger.error(f"❌ خطأ في إنشاء قاعدة البيانات: {e}")

# ============ دوال مساعدة ============

def test_mikrotik_connection(router):
    """اختبار الاتصال بـ Mikrotik"""
    try:
        conn = librouteros.connect(
            host=router.ip_address,
            username=router.username,
            password=router.password,
            port=router.port,
            timeout=5
        )
        conn.close()
        logger.info(f"✅ اتصال ناجح مع {router.name}")
        return True
    except Exception as e:
        logger.warning(f"⚠️ فشل الاتصال بـ {router.name}: {str(e)}")
        return False

def get_master_router():
    """جلب الراوتر الرئيسي (RADIUS Server)"""
    try:
        return Router.query.filter_by(is_master=True).first()
    except Exception as e:
        logger.error(f"❌ خطأ في جلب الراوتر الرئيسي: {e}")
        return None

def get_mikrotik_users(router):
    """جلب المستخدمين من Mikrotik"""
    try:
        if not test_mikrotik_connection(router):
            return []
        
        conn = librouteros.connect(
            host=router.ip_address,
            username=router.username,
            password=router.password,
            port=router.port,
            timeout=10
        )
        users = conn('/user/print')
        conn.close()
        return users if users else []
    except Exception as e:
        logger.error(f"❌ خطأ في جلب المستخدمين: {e}")
        return []

def get_active_sessions(router):
    """جلب الجلسات النشطة"""
    try:
        conn = librouteros.connect(
            host=router.ip_address,
            username=router.username,
            password=router.password,
            port=router.port,
            timeout=10
        )
        sessions = conn('/ppp/active/print')
        conn.close()
        return len(sessions) if sessions else 0
    except Exception as e:
        logger.error(f"❌ خطأ في جلب الجلسات: {e}")
        return 0

# ============ المسارات (Routes) ============

@app.before_request
def check_session():
    """التحقق من جلسة المستخدم"""
    if not session.get('admin_id') and request.endpoint not in ['login', 'static']:
        if request.endpoint != 'login':
            return redirect(url_for('login'))

@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if username and password:
            admin = AdminUser.query.filter_by(username=username).first()
            if admin and admin.password == password:
                session['admin_id'] = admin.id
                session['admin_name'] = admin.username
                flash('✅ تم تسجيل الدخول بنجاح', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('❌ اسم المستخدم أو كلمة المرور خاطئة', 'danger')
        else:
            flash('❌ الرجاء إدخال جميع البيانات', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('✅ تم تسجيل الخروج بنجاح', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    try:
        # جلب الإحصائيات
        routers_list = Router.query.all()
        routers_count = len(routers_list)
        routers_online = sum(1 for r in routers_list if test_mikrotik_connection(r))
        
        master = get_master_router()
        sub_count = 0
        active_sessions = 0
        subscribers_preview = []
        new_users_today = 0

        if master:
            users = get_mikrotik_users(master)
            sub_count = len(users)
            active_sessions = get_active_sessions(master)
            subscribers_preview = users[-8:] if len(users) > 8 else users
            
            # حساب المستخدمين الجدد اليوم
            today_users = Subscriber.query.filter(
                db.func.date(Subscriber.created_at) == datetime.utcnow().date()
            ).count()
            new_users_today = today_users

        return render_template(
            'dashboard.html',
            routers_count=routers_count,
            routers_online=routers_online,
            sub_count=sub_count,
            active_sessions=active_sessions,
            subscribers=subscribers_preview,
            today_revenue=0,
            active_vouchers=0,
            new_users_today=new_users_today,
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

        try:
            port = int(port)
        except ValueError:
            port = 8728

        # التحقق من وجود راوتر بنفس الاسم
        if Router.query.filter_by(name=name).first():
            flash('❌ اسم الراوتر موجود مسبقاً', 'danger')
            return redirect(url_for('routers'))

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
            
            # اختبار الاتصال
            if test_mikrotik_connection(new_router):
                new_router.status = 'online'
                flash(f'✅ تمت إضافة الراوتر "{name}" والاتصال ناجح', 'success')
            else:
                new_router.status = 'offline'
                flash(f'⚠️ تمت إضافة الراوتر "{name}" لكن الاتصال فشل', 'warning')
            
            db.session.add(new_router)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ خطأ في إضافة الراوتر: {e}")
            flash(f'❌ خطأ: {str(e)}', 'danger')
        
        return redirect(url_for('routers'))

    try:
        routers_list = Router.query.all()
        for router in routers_list:
            router.status = 'online' if test_mikrotik_connection(router) else 'offline'
    except Exception as e:
        logger.error(f"❌ خطأ في جلب الراوترات: {e}")
        routers_list = []

    return render_template('routers.html', routers=routers_list)

@app.route('/routers/set_master/<int:router_id>')
def set_master_router(router_id):
    try:
        Router.query.update({Router.is_master: False})
        router = Router.query.get_or_404(router_id)
        router.is_master = True
        db.session.commit()
        flash(f'✅ "{router.name}" الآن سيرفر RADIUS الرئيسي', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ خطأ: {e}")
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('routers'))

@app.route('/routers/delete/<int:router_id>')
def delete_router(router_id):
    try:
        router = Router.query.get_or_404(router_id)
        router_name = router.name
        db.session.delete(router)
        db.session.commit()
        flash(f'✅ تم حذف "{router_name}" بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ خطأ في الحذف: {e}")
        flash(f'❌ خطأ: {str(e)}', 'danger')
    return redirect(url_for('routers'))

@app.route('/subscribers')
def subscribers():
    search = request.args.get('q', '').strip()
    master = get_master_router()
    subscribers_list = []
    error_msg = None

    if not master:
        error_msg = '⚠️ لم يتم تحديد راوتر رئيسي'
    else:
        try:
            subscribers_list = get_mikrotik_users(master)
            if search:
                subscribers_list = [
                    s for s in subscribers_list
                    if search.lower() in s.get('name', '').lower()
                ]
        except Exception as e:
            logger.error(f"❌ خطأ: {e}")
            error_msg = f'❌ خطأ في الاتصال: {str(e)}'

    
