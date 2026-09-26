import os
import logging
import traceback
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
import mikrotik_api

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'zinar-secret-key-123')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

database_url = os.environ.get('DATABASE_URL', 'sqlite:///zinar.db')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

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

# ----------------- نماذج قاعدة البيانات -----------------
class Router(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    ip_address = db.Column(db.String(50), nullable=False)
    username = db.Column(db.String(50), nullable=False)
    password = db.Column(db.String(50), nullable=False)
    port = db.Column(db.Integer, default=8728)
    is_master = db.Column(db.Boolean, default=False)  # سيرفر User Manager الرئيسي (RADIUS)

with app.app_context():
    db.create_all()

def get_master_router():
    """يرجع الراوتر المعرّف كسيرفر User Manager الرئيسي، أو None إذا ما في."""
    return Router.query.filter_by(is_master=True).first()

# ----------------- المسارات -----------------
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
    except Exception:
        logger.exception("فشل في جلب الراوترات لصفحة dashboard")
        routers_list = []
        routers_count = 0

    live_stats = mikrotik_api.get_all_routers_stats(routers_list)
    active_sessions = live_stats['totals']['ppp_active'] + live_stats['totals']['hotspot_active']
    routers_online = live_stats['totals']['online_count']

    # عدد المشتركين الحقيقي من User Manager (مش من قاعدة بيانات منفصلة)
    sub_count = 0
    active_subs = 0
    subscribers_preview = []
    master = get_master_router()
    if master:
        result = mikrotik_api.get_userman_users(master)
        if result.get('success'):
            raw_users = result.get('raw', [])
            sub_count = len(raw_users)
            active_subs = sub_count  # User Manager ما بيرجع حالة enabled/disabled مباشرة بهالقراءة البسيطة
            subscribers_preview = raw_users[-8:][::-1]

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
        logger.error("فشل في عرض dashboard.html: %s", e)
        logger.error(traceback.format_exc())
        return f"<h2>خطأ في عرض لوحة التحكم</h2><pre>{traceback.format_exc()}</pre>", 500

@app.route('/routers', methods=['GET', 'POST'])
def routers():
    if request.method == 'POST':
        name = request.form.get('name')
        ip_address = request.form.get('ip') or request.form.get('ip_address')
        username = request.form.get('username')
        password = request.form.get('password')
        port = request.form.get('port', 8728)
        is_master = request.form.get('is_master') == 'on'
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = 8728

        if name and ip_address:
            if is_master:
                # راوتر واحد بس ممكن يكون رئيسي بأي وقت
                Router.query.update({Router.is_master: False})
            new_router = Router(name=name, ip_address=ip_address, username=username,
                                 password=password, port=port, is_master=is_master)
            db.session.add(new_router)
            db.session.commit()
            flash('تمت إضافة الراوتر بنجاح', 'success')
        else:
            flash('لازم تعبي اسم الراوتر وعنوان الآيباد على الأقل', 'danger')
        return redirect(url_for('routers'))

    try:
        routers_list = Router.query.all()
    except Exception:
        logger.exception("فشل في جلب قائمة الراوترات")
        routers_list = []

    connection_status = {}
    for r in routers_list:
        connection_status[r.id] = mikrotik_api.test_connection(r)

    return render_template('routers.html', routers=routers_list, connection_status=connection_status)

@app.route('/routers/set_master/<int:id>')
def set_master_router(id):
    Router.query.update({Router.is_master: False})
    router = Router.query.get_or_404(id)
    router.is_master = True
    db.session.commit()
    flash(f'صار "{router.name}" هو سيرفر User Manager الرئيسي', 'success')
    return redirect(url_for('routers'))

@app.route('/packages', methods=['GET', 'POST'])
def packages():
    master = get_master_router()

    if request.method == 'POST':
        if not master:
            flash('لازم تحدد راوتر رئيسي أولاً من صفحة الراوترات', 'danger')
            return redirect(url_for('routers'))

        name = request.form.get('name')
        price = request.form.get('price', '0')
        validity = request.form.get('validity', '0')

        if name:
            result = mikrotik_api.add_userman_profile(master, name, price, validity)
            if result.get('success'):
                flash('تمت إضافة الباقة بنجاح', 'success')
            else:
                flash(f"فشلت الإضافة: {result.get('error')}", 'danger')
        else:
            flash('لازم تكتب اسم الباقة', 'danger')
        return redirect(url_for('packages'))

    profiles = []
    if master:
        result = mikrotik_api.get_userman_profiles(master)
        if result.get('success'):
            profiles = result.get('raw', [])
    return render_template('packages.html', profiles=profiles, has_master=master is not None)

@app.route('/packages/delete/<name>')
def delete_package(name):
    master = get_master_router()
    if master:
        result = mikrotik_api.remove_userman_profile(master, name)
        if result.get('success'):
            flash('تم حذف الباقة بنجاح', 'success')
        else:
            flash(f"فشل الحذف: {result.get('error')}", 'danger')
    return redirect(url_for('packages'))

@app.route('/packages/edit/<name>', methods=['POST'])
def edit_package(name):
    master = get_master_router()
    if master:
        price = request.form.get('price')
        validity = request.form.get('validity')
        result = mikrotik_api.edit_userman_profile(master, name, price, validity)
        if result.get('success'):
            flash('تم تعديل الباقة بنجاح', 'success')
        else:
            flash(f"فشل التعديل: {result.get('error')}", 'danger')
    return redirect(url_for('packages'))

@app.route('/subscribers')
def subscribers():
    search_query = request.args.get('q', '').strip()
    master = get_master_router()
    subscribers_list = []
    error_message = None

    if not master:
        error_message = 'لازم تحدد راوتر كـ "سيرفر رئيسي" أولاً من صفحة الراوترات.'
    else:
        result = mikrotik_api.get_userman_users(master)
        if result.get('success'):
            subscribers_list = result.get('raw', [])
            if search_query:
                subscribers_list = [
                    s for s in subscribers_list
                    if search_query.lower() in s.get('username', '').lower()
                ]
        else:
            error_message = f"تعذر الاتصال بالراوتر الرئيسي: {result.get('error')}"

    profiles = []
    if master:
        p_result = mikrotik_api.get_userman_profiles(master)
        if p_result.get('success'):
            profiles = p_result.get('raw', [])

    return render_template('subscribers.html', subscribers=subscribers_list,
                            search_query=search_query, error_message=error_message,
                            has_master=master is not None, profiles=profiles)

@app.route('/subscribers/edit/<username>', methods=['POST'])
def edit_subscriber(username):
    master = get_master_router()
    if master:
        password = request.form.get('password')
        profile = request.form.get('profile')
        result = mikrotik_api.edit_userman_user(master, username, password or None, profile or None)
        if result.get('success'):
            flash('تم تعديل المشترك بنجاح', 'success')
        else:
            flash(f"فشل التعديل: {result.get('error')}", 'danger')
    return redirect(url_for('subscribers'))

@app.route('/add_subscriber', methods=['GET', 'POST'])
def add_subscriber():
    master = get_master_router()

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        profile = request.form.get('profile')

        if not master:
            flash('لازم تحدد راوتر رئيسي أولاً من صفحة الراوترات', 'danger')
            return redirect(url_for('routers'))

        if username and password:
            result = mikrotik_api.add_userman_user(master, username, password, profile)
            if result.get('success'):
                flash('تمت إضافة المشترك بنجاح على الراوتر مباشرة', 'success')
            else:
                flash(f"فشلت الإضافة: {result.get('error')}", 'danger')
        else:
            flash('لازم تعبي اسم المستخدم وكلمة المرور على الأقل', 'danger')
        return redirect(url_for('subscribers'))

    profiles = []
    if master:
        result = mikrotik_api.get_userman_profiles(master)
        if result.get('success'):
            profiles = result.get('raw', [])

    return render_template('add_subscriber.html', has_master=master is not None, profiles=profiles)

@app.route('/delete_subscriber/<username>')
def delete_subscriber(username):
    master = get_master_router()
    if master:
        result = mikrotik_api.remove_userman_user(master, username)
        if result.get('success'):
            flash('تم حذف المشترك بنجاح', 'success')
        else:
            flash(f"فشل الحذف: {result.get('error')}", 'danger')
    return redirect(url_for('subscribers'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
