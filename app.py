import os
import logging
import traceback
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import librouteros  # مكتبة للاتصال بـ Mikrotik

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'zinar-secret-key-123')

# تفعيل CORS للاتصال من Frontend
CORS(app, resources={r"/api/*": {"origins": "*"}})

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ إعدادات قاعدة البيانات ============
database_url = os.environ.get('DATABASE_URL', 'sqlite:///zinar.db')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
if database_url and database_url.startswith('postgresql://') and '+psycopg' not in database_url:
    database_url = database_url.replace('postgresql://', 'postgresql+psycopg2://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ============ ترجمة النصوص ============
def t(key):
    translations = {
        'brand_sub': 'نظام إدارة المشتركين',
        'dashboard': 'لوحة التحكم',
        'routers': 'الراوترات',
        'subscribers': 'المشتركين',
        'add_subscriber': 'إضافة مشترك',
        'packages': 'الباقات',
        'login': 'تسجيل الدخول'
    }
    return translations.get(key, key)

app.jinja_env.globals['t'] = t
app.jinja_env.filters['t'] = t

# ============ نماذج قاعدة البيانات ============
class Router(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    ip_address = db.Column(db.String(50), nullable=False)
    username = db.Column(db.String(50), nullable=False)
    password = db.Column(db.String(100), nullable=False)
    port = db.Column(db.Integer, default=8728)
    is_master = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

class AdminUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

with app.app_context():
    db.create_all()
    # إنشاء admin افتراضي إذا ما كان موجود
    if not AdminUser.query.filter_by(username='admin').first():
        admin = AdminUser(username='admin', password='admin123')
        db.session.add(admin)
        db.session.commit()

# ============ دوال مساعدة ============
def get_master_router():
    """ترجع الراوتر الرئيسي"""
    return Router.query.filter_by(is_master=True).first()

def test_mikrotik_connection(router):
    """اختبار الاتصال بـ Mikrotik"""
    try:
        conn = librouteros.connect(
            host=router.ip_address,
            username=router.username,
            password=router.password,
            port=router.port
        )
        conn.close()
        return True
    except Exception as e:
        logger.error(f"خطأ في الاتصال بـ {router.name}: {e}")
        return False

def get_mikrotik_users(router):
    """جلب المستخدمين من Mikrotik User Manager"""
    try:
        conn = librouteros.connect(
            host=router.ip_address,
            username=router.username,
            password=router.password,
            port=router.port
        )
        users = conn('/user/print')
        conn.close()
        return users
    except Exception as e:
        logger.error(f"خطأ في جلب المستخدمين: {e}")
        return []

def get_ppp_connections(router):
    """جلب اتصالات PPP النشطة"""
    try:
        conn = librouteros.connect(
            host=router.ip_address,
            username=router.username,
            password=router.password,
            port=router.port
        )
        sessions = conn('/ppp/secret/print')
        conn.close()
        return len(sessions)
    except Exception as e:
        logger.error(f"خطأ في جلب الجلسات: {e}")
        return 0

# ============ المسارات / Routes ============

@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        return redirect(url_for('dashboard'))
    return render_template('login.html') if os.path.exists('templates/login.html') else redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    try:
        routers_list = Router.query.all()
        routers_count = len(routers_list)
        routers_online = sum(1 for r in routers_list if test_mikrotik_connection(r))
    except Exception as e:
        logger.exception("خطأ في جلب الراوترات")
        routers_list = []
        routers_count = 0
        routers_online = 0

    master = get_master_router()
    sub_count = 0
    active_subs = 0
    subscribers_preview = []
    active_sessions = 0

    if master:
        subscribers = get_mikrotik_users(master)
        sub_count = len(subscribers)
        active_subs = sub_count
        subscribers_preview = subscribers[-8:] if len(subscribers) > 8 else subscribers
        active_sessions = get_ppp_connections(master)

    try:
        return render_template(
            'dashboard.html',
            routers_count=routers_count,
            routers_online=routers_online,
            sub_count=sub_count,
            active_subs=active_subs,
            subscribers=subscribers_preview,
            active_sessions=active_sessions,
            today_revenue=0,
            active_vouchers=0,
            has_master=master is not None
        )
    except Exception as e:
        logger.error(f"خطأ في عرض dashboard: {e}")
        return f"<h2>خطأ في عرض لوحة التحكم</h2><pre>{traceback.format_exc()}</pre>", 500

@app.route('/routers', methods=['GET', 'POST'])
def routers():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        ip_address = request.form.get('ip_address', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        port = request.form.get('port', '8728')
        is_master = request.form.get('is_master') == 'on'

        try:
            port = int(port)
        except (TypeError, ValueError):
            port = 8728

        if not name or not ip_address:
            flash('لازم تعبي: اسم الراوتر وعنوان IP', 'danger')
            return redirect(url_for('routers'))

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
        flash(f'✅ تمت إضافة الراوتر "{name}" بنجاح', 'success')
        return redirect(url_for('routers'))

    try:
        routers_list = Router.query.all()
    except Exception as e:
        logger.exception("خطأ في جلب الراوترات")
        routers_list = []

    connection_status = {}
    for r in routers_list:
        connection_status[r.id] = test_mikrotik_connection(r)

    return render_template('routers.html', routers=routers_list, connection_status=connection_status)

@app.route('/routers/set_master/<int:id>')
def set_master_router(id):
    try:
        Router.query.update({Router.is_master: False})
        router = Router.query.get_or_404(id)
        router.is_master = True
        db.session.commit()
        flash(f'✅ "{router.name}" الآن سيرفر RADIUS الرئيسي', 'success')
    except Exception as e:
        logger.error(f"خطأ في تحديد الراوتر الرئيسي: {e}")
        flash('❌ فشل تحديث الراوتر الرئيسي', 'danger')
    return redirect(url_for('routers'))

@app.route('/routers/delete/<int:id>')
def delete_router(id):
    try:
        router = Router.query.get_or_404(id)
        db.session.delete(router)
        db.session.commit()
        flash(f'✅ تم حذف الراوتر "{router.name}" بنجاح', 'success')
    except Exception as e:
        logger.error(f"خطأ في حذف الراوتر: {e}")
        flash('❌ فشل حذف الراوتر', 'danger')
    return redirect(url_for('routers'))

@app.route('/subscribers')
def subscribers():
    search_query = request.args.get('q', '').strip()
    master = get_master_router()
    subscribers_list = []
    error_message = None

    if not master:
        error_message = '⚠️ لازم تحدد راوتر رئيسي من صفحة الراوترات'
    else:
        subscribers_list = get_mikrotik_users(master)
        if search_query:
            subscribers_list = [
                s for s in subscribers_list
                if search_query.lower() in s.get('name', '').lower()
            ]

    return render_template(
        'subscribers.html',
        subscribers=subscribers_list,
        search_query=search_query,
        error_message=error_message,
        has_master=master is not None
    )

@app.route('/subscribers/add', methods=['GET', 'POST'])
def add_subscriber():
    master = get_master_router()

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not master:
            flash('⚠️ لازم تحدد راوتر رئيسي أولاً', 'danger')
            return redirect(url_for('routers'))

        if not username or not password:
            flash('❌ لازم تعبي: الاسم وكلمة المرور', 'danger')
            return redirect(url_for('add_subscriber'))

        try:
            conn = librouteros.connect(
                host=master.ip_address,
                username=master.username,
                password=master.password,
                port=master.port
            )
            conn('/user/add', name=username, password=password)
            conn.close()
            flash(f'✅ تم إضافة المستخدم "{username}" بنجاح', 'success')
            return redirect(url_for('subscribers'))
        except Exception as e:
            logger.error(f"خطأ في إضافة مستخدم: {e}")
            flash(f'❌ فشل: {str(e)}', 'danger')
            return redirect(url_for('add_subscriber'))

    return render_template('add_subscriber.html', has_master=master is not None)

@app.route('/subscribers/delete/<username>')
def delete_subscriber(username):
    master = get_master_router()
    if master:
        try:
            conn = librouteros.connect(
                host=master.ip_address,
                username=master.username,
                password=master.password,
                port=master.port
            )
            conn('/user/remove', name=username)
            conn.close()
            flash(f'✅ تم حذف "{username}" بنجاح', 'success')
        except Exception as e:
            logger.error(f"خطأ في حذف مستخدم: {e}")
            flash(f'❌ فشل الحذف: {str(e)}', 'danger')
    return redirect(url_for('subscribers'))

# ============ API للـ Frontend (AJAX) ============

@app.route('/admin/profile', methods=['POST'])
def update_admin_profile():
    """API لتحديث بيانات Admin من الـ Frontend"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()

        if not username:
            return jsonify({'success': False, 'error': 'اسم المستخدم مطلوب'}), 400

        admin = AdminUser.query.first()
        if not admin:
            admin = AdminUser(username=username, password=password or 'admin123')
            db.session.add(admin)
        else:
            admin.username = username
            if password:
                admin.password = password
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم التحديث بنجاح'}), 200

    except Exception as e:
        logger.error(f"خطأ في تحديث البيانات: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """API لجلب الإحصائيات"""
    try:
        routers_count = Router.query.count()
        routers_online = sum(1 for r in Router.query.all() if test_mikrotik_connection(r))
        
        master = get_master_router()
        sub_count = len(get_mikrotik_users(master)) if master else 0
        active_sessions = get_ppp_connections(master) if master else 0

        return jsonify({
            'success': True,
            'routers_count': routers_count,
            'routers_online': routers_online,
            'sub_count': sub_count,
            'active_sessions': active_sessions
        }), 200
    except Exception as e:
        logger.error(f"خطأ في جلب الإحصائيات: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(error):
    logger.error(f"خطأ في السيرفر: {error}")
    return render_template('500.html'), 500

if __name__ == '__main__':
