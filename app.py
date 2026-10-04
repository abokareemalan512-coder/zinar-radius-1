# app.py — DB Master + API + Automatic Kick
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
import radius_sync

# ============ الإعدادات ============
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'zinar-secret-key-2024')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ Database ============
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

from api_sync import sync_bp
app.register_blueprint(sync_bp)

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


class TrafficCache(db.Model):
    __tablename__ = 'traffic_cache'
    id = db.Column(db.Integer, primary_key=True)
    iface = db.Column(db.String(50), default='ether1')
    up = db.Column(db.Float, default=0.0)
    down = db.Column(db.Float, default=0.0)
    ts = db.Column(db.Integer, default=0)
    ifaces_json = db.Column(db.Text, default='{}')


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


# ============ Helpers ============

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


# ============ Kick via SSH ============

def kick_user_via_ssh(router, username, user_type='pppoe'):
    """
    قطع اتصال مستخدم نشط على الراوتر عبر SSH.
    لا يحذف الحساب — فقط kick.
    """
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
    import os
    if os.environ.get("RENDER") == "true": return
    """kick مشترك على كل الراوترات النشطة (لأنه قد يكون متصلًا بأي راوتر)"""
    if not sub:
        return

    # kick على الراوتر المرتبط (إن وُجد)
    if sub.router_id:
        r = Router.query.get(sub.router_id)
        if r:
            kick_user_via_ssh(r, sub.username, sub.user_type or 'pppoe')

    # kick على كل الراوترات النشطة الأخرى (لتغطية كل الحالات)
    other_routers = Router.query.filter(
        Router.is_active == True,
        Router.id != (sub.router_id or 0)
    ).all()
    for r in other_routers:
        try:
            kick_user_via_ssh(r, sub.username, sub.user_type or 'pppoe')
        except Exception:
            pass


# ============ Init ============

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
            logger.info("✅ تم تهيئة قاعدة البيانات")
        except Exception as e:
            logger.error(f"❌ {e}")


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
    if request.endpoint is None: return
    if request.endpoint.startswith('static'): return
    if request.path.startswith('/api/'): return
    public = ('login', 'logout', 'mobile', 'mobile_view', 'api_traffic', 'api_traffic_update', 'api_ifaces', 'sync.get_subscribers', 'sync.mark_first_use', 'api_auth', 'api_log')
    if request.endpoint in public: return
    if not session.get('admin_id'):
        return redirect(url_for('login'))


# ============ Auth ============

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
            flash('✅ تم تسجيل الدخول', 'success')
            return redirect(url_for('dashboard'))
        flash('❌ بيانات غير صحيحة', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('✅ تم تسجيل الخروج', 'success')
    return redirect(url_for('login'))


# ============ Dashboard ============

# ============ Traffic Cache (ORM) ============
@app.route('/api/traffic')
def api_traffic():
    db.session.remove()
    iface = request.args.get('iface', 'ether1')
    try:
        row = TrafficCache.query.first()
        if row:
            import json as _j
            ifaces = _j.loads(row.ifaces_json or '{}')
            d = ifaces.get(iface, {'up': 0, 'down': 0})
            return jsonify({'up': d.get('up',0), 'down': d.get('down',0), 'ts': row.ts, 'iface': iface})
    except Exception:
        pass
    return jsonify({'up': 0.0, 'down': 0.0, 'ts': 0, 'iface': iface})

@app.route('/api/ifaces')
def api_ifaces():
    db.session.remove()
    try:
        import json as _j
        row = TrafficCache.query.first()
        if row:
            ifaces = _j.loads(row.ifaces_json or '{}')
            return jsonify({'ifaces': list(ifaces.keys())})
    except Exception:
        pass
    return jsonify({'ifaces': ['ether1', 'ether2', 'ether3', 'bridge']})

@app.route('/api/traffic/update', methods=['POST'])
def api_traffic_update():
    db.session.remove()
    token = request.headers.get('X-Sync-Token')
    if token != 'zinar-sync-token-2026':
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json() or {}
    try:
        import json as _j
        ifaces = data.get('ifaces', {})
        total_up = sum(v.get('up',0) for v in ifaces.values()) if ifaces else data.get('up',0)
        total_down = sum(v.get('down',0) for v in ifaces.values()) if ifaces else data.get('down',0)
        row = TrafficCache.query.first()
        if not row:
            row = TrafficCache()
            db.session.add(row)
        row.up = total_up
        row.down = total_down
        row.ts = data.get('ts', 0)
        row.iface = data.get('iface', 'ether1')
        if ifaces:
            row.ifaces_json = _j.dumps(ifaces)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    return jsonify({'ok': True})

@app.route('/dashboard')
def dashboard():
    try:
        routers_list = Router.query.all()
        routers_count = len(routers_list)
        master = Router.query.filter_by(is_master=True).first()
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

        preview = Subscriber.query.order_by(Subscriber.created_at.desc()).limit(8).all()

        return render_template(
            'dashboard.html',
            routers_count=routers_count, routers_online=routers_count,
            sub_count=sub_count, active_subs=active_subs, active_sessions=active_subs,
            today_revenue=today_revenue, active_vouchers=0,
            new_users_today=new_users_today, pending_pays=pending_pays,
            subscribers=preview, has_master=master is not None,
            admin_name=session.get('admin_name', 'مدير'),
        )
    except Exception as e:
        logger.error(f"❌ dashboard: {e}")
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
        flash('✅ تم التحديث', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('dashboard'))


# ============ Routers (DB only) ============

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

        try: port = int(port)
        except ValueError: port = 22

        try:
            if is_master:
                Router.query.update({Router.is_master: False}, synchronize_session=False)
            db.session.add(Router(name=name, ip_address=ip, username=un,
                                  password=pw, port=port, is_master=is_master, is_active=True))
            db.session.commit()
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
        flash('✅ تم التحديث', 'success')
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
        if pw: r.password = pw
        try: r.port = int(port)
        except ValueError: r.port = 22

        db.session.commit()
        flash('✅ تم التحديث', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('routers'))


@app.route('/routers/delete/<int:router_id>')
def delete_router(router_id):
    try:
        r = Router.query.get_or_404(router_id)
        db.session.delete(r)
        db.session.commit()
        flash('✅ تم الحذف من قاعدة البيانات', 'success')
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
        if expired: db.session.commit()

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
        logger.error(f"❌ {e}")
        subs = []

    return render_template('subscribers.html',
        subscribers=subs,
        routers={r.id: r for r in Router.query.all()},
        packages=Package.query.order_by(Package.name).all(),
        search=search, now=now, filter_type=ft)


@app.route('/add-subscriber', methods=['GET', 'POST'])
@app.route('/subscribers/add', methods=['GET', 'POST'])
def add_subscriber():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        un = request.form.get('username', '').strip()
        pw = request.form.get('password', '').strip()
        pkg = request.form.get('package', '').strip()
        ut = request.form.get('user_type', 'pppoe').strip()

        if ut not in ('pppoe', 'hotspot'): ut = 'pppoe'
        if not un or not pw:
            flash('❌ الاسم وكلمة المرور مطلوبان', 'danger')
            return redirect(url_for('add_subscriber'))
        if Subscriber.query.filter_by(username=un).first():
            flash(f'❌ "{un}" موجود', 'danger')
            return redirect(url_for('add_subscriber'))

        try:
            db.session.add(Subscriber(
                name=name or un, username=un, password=pw,
                package=pkg, user_type=ut,
                expires_at=None, status='active'
            ))
            db.session.commit()
            radius_sync.sync_user(un, pw)
            flash(f'✅ "{un}" أُضيف — 📌 في قاعدة البيانات فقط', 'success')
            return redirect(url_for('subscribers'))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ {e}', 'danger')

    return render_template('add_subscriber.html',
        packages=Package.query.order_by(Package.name).all(),
        routers=Router.query.order_by(Router.name).all())


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

        if ut not in ('pppoe', 'hotspot'): ut = 'pppoe'
        if cm not in ('numbers', 'letters', 'mixed'): cm = 'numbers'
        if pm not in ('random', 'same_as_username', 'fixed'): pm = 'random'

        try:
            pl = int(pl)
            if pl < 4 or pl > 20: pl = 6
        except ValueError: pl = 6

        try:
            rl = int(request.form.get('random_length', '6'))
            if rl < 4 or rl > 20: rl = 6
        except ValueError: rl = 6

        try: cnt = int(cnt)
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
            if pm == 'same_as_username': pw = un
            elif pm == 'fixed': pw = fp
            elif pm == 'random': pw = ''.join(random.choices(N, k=pl))
            else: pw = un

            if Subscriber.query.filter_by(username=un).first():
                failed += 1; continue
            try:
                db.session.add(Subscriber(name=un, username=un, password=pw,
                                          package=pkg, user_type=ut,
                                          expires_at=None, status='active'))
                created += 1
            except Exception:
                failed += 1

        db.session.commit()
        for un in usernames:
            sub = Subscriber.query.filter_by(username=un).first()
            if sub:
                radius_sync.sync_user(sub.username, sub.password)
        flash(f'✅ {created} مشترك' + (f' — فشل {failed}' if failed else ''),
              'success' if not failed else 'warning')
        return redirect(url_for('subscribers'))

    return render_template('bulk_add.html',
        packages=Package.query.order_by(Package.name).all(),
        routers=Router.query.order_by(Router.name).all())


@app.route('/subscribers/toggle/<int:sub_id>')
def toggle_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        if sub.status == 'active':
            sub.status = 'paused'
            db.session.commit()
            radius_sync.pause_user(sub.username)
            # 👢 kick فوري
            kick_subscriber(sub)
            flash(f'⏸ "{sub.username}" موقوف وتم قطعه', 'warning')
        else:
            if sub.expires_at and sub.expires_at < datetime.utcnow():
                flash('⚠️ منتهي', 'danger')
            else:
                sub.status = 'active'
                db.session.commit()
                radius_sync.resume_user(sub.username, sub.password)
                flash(f'▶ "{sub.username}" نشط', 'success')
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
        # 👢 kick لإعادة الاتصال من جديد
        kick_subscriber(sub)
        flash('🔄 تم التصفير — ⏳ سيبدأ من جديد', 'success')
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
        flash(f'➕ ينتهي {sub.expires_at.strftime("%Y-%m-%d")}', 'success')
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
        if nun: sub.username = nun
        pw = request.form.get('password', '').strip()
        if pw: sub.password = pw
        pkg = request.form.get('package', '').strip()
        if pkg: sub.package = pkg
        db.session.commit()
        flash('✅ تم التحديث في قاعدة البيانات', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


@app.route('/subscribers/delete/<int:sub_id>')
def delete_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        # 👢 kick قبل الحذف
        kick_subscriber(sub)
        radius_sync.delete_user(sub.username)
        db.session.delete(sub)
        db.session.commit()
        flash('✅ تم الحذف وقطع الاتصال', 'success')
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
                if kick_subscriber(sub):
                    kicked += 1
            except Exception:
                pass
            radius_sync.delete_user(sub.username)
            db.session.delete(sub)
            deleted += 1
        db.session.commit()
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
                seen.add(s.id); unique.append(s)

        if not unique:
            flash('ℹ️ لا يوجد منتهون', 'info')
            return redirect(url_for('subscribers'))

        deleted = 0
        for sub in unique:
            try:
                kick_subscriber(sub)
            except Exception:
                pass
            radius_sync.delete_user(sub.username)
            db.session.delete(sub); deleted += 1
        db.session.commit()
        flash(f'🗑 تم حذف {deleted} منتهي', 'success')
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
            subs = Subscriber.query.filter(Subscriber.id.in_(idl))\
                                   .order_by(Subscriber.created_at.desc()).all()
        except Exception: subs = []
    else:
        q = Subscriber.query
        if ft in ('pppoe', 'hotspot'):
            q = q.filter_by(user_type=ft)
        subs = q.order_by(Subscriber.created_at.desc()).all()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if format == 'csv':
        out = io.StringIO(); out.write('\ufeff')
        w = csv.writer(out)
        w.writerow(['#', 'الاسم', 'المستخدم', 'المرور', 'الباقة', 'النوع', 'الحالة', 'الانتهاء'])
        for i, s in enumerate(subs, 1):
            w.writerow([i, s.name or '', s.username, s.password,
                        s.package or '', s.user_type or 'pppoe', s.status,
                        s.expires_at.strftime('%Y-%m-%d') if s.expires_at else '⏳'])
        out.seek(0)
        return send_file(io.BytesIO(out.getvalue().encode('utf-8')),
                         mimetype='text/csv', as_attachment=True,
                         download_name=f'subs_{ts}.csv')

    elif format == 'txt':
        lines = ['=' * 60, 'ZINAR — قائمة المشتركين',
                 datetime.now().strftime("%Y-%m-%d %H:%M"),
                 f'العدد: {len(subs)}', '=' * 60, '']
        for i, s in enumerate(subs, 1):
            lines.append(f'{i}. {s.name or s.username}')
            lines.append(f'   User: {s.username}')
            lines.append(f'   Pass: {s.password}')
            lines.append(f'   Pkg : {s.package or "-"}')
            if s.expires_at: lines.append(f'   Exp : {s.expires_at.strftime("%Y-%m-%d")}')
            lines.append('-' * 60)
        return send_file(io.BytesIO('\n'.join(lines).encode('utf-8')),
                         mimetype='text/plain', as_attachment=True,
                         download_name=f'subs_{ts}.txt')

    elif format == 'print':
        return render_template('print_subscribers.html',
                               subscribers=subs, now=datetime.utcnow(),
                               filter_type=ft)

    flash('❌ صيغة غير مدعومة', 'danger')
    return redirect(url_for('subscribers'))


# ============ Packages ============

@app.route('/packages')
def packages():
    return render_template('packages.html',
                           packages=Package.query.order_by(Package.id).all())


@app.route('/packages/add', methods=['POST'])
def add_package():
    name = request.form.get('name', '').strip()
    speed = request.form.get('speed', '').strip()
    price = request.form.get('price', '0').strip()
    dur = request.form.get('duration', '1').strip()
    unit = request.form.get('duration_unit', 'days').strip()
    ut = request.form.get('user_type', 'pppoe').strip()

    if unit not in ('days', 'months'): unit = 'days'
    if ut not in ('pppoe', 'hotspot'): ut = 'pppoe'
    if not name:
        flash('❌ اسم الباقة مطلوب', 'danger')
        return redirect(url_for('packages'))
    if Package.query.filter_by(name=name).first():
        flash('❌ الاسم موجود', 'danger')
        return redirect(url_for('packages'))

    try:
        db.session.add(Package(name=name, speed=speed, price=float(price or 0),
                               duration=int(dur or 1), duration_unit=unit, user_type=ut))
        db.session.commit()
        flash(f'✅ تم إضافة "{name}"', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('packages'))


@app.route('/packages/update/<int:pkg_id>', methods=['POST'])
def update_package(pkg_id):
    try:
        p = Package.query.get_or_404(pkg_id)
        name = request.form.get('name', '').strip()
        speed = request.form.get('speed', '').strip()
        price = request.form.get('price', '0').strip()
        dur = request.form.get('duration', '1').strip()
        unit = request.form.get('duration_unit', 'days').strip()
        ut = request.form.get('user_type', 'pppoe').strip()

        if unit not in ('days', 'months'): unit = 'days'
        if ut not in ('pppoe', 'hotspot'): ut = 'pppoe'
        if not name:
            flash('❌ الاسم مطلوب', 'danger')
            return redirect(url_for('packages'))
        if Package.query.filter(Package.name == name, Package.id != pkg_id).first():
            flash('❌ الاسم موجود', 'danger')
            return redirect(url_for('packages'))

        p.name = name
        p.speed = speed
        p.price = float(price or 0)
        p.duration = int(dur or 1)
        p.duration_unit = unit
        p.user_type = ut
        db.session.commit()
        flash('✅ تم التحديث', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('packages'))


@app.route('/packages/delete/<int:pkg_id>')
def delete_package(pkg_id):
    try:
        p = Package.query.get_or_404(pkg_id)
        db.session.delete(p)
        db.session.commit()
        flash('✅ تم الحذف', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('packages'))


# ============ Payments ============

@app.route('/payments')
def payments():
    return render_template('payments.html',
        payments=Payment.query.order_by(Payment.created_at.desc()).all())


@app.route('/payments/<int:pid>/complete', methods=['POST'])
def complete_payment(pid):
    try:
        p = Payment.query.get_or_404(pid)
        p.status = 'completed'
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============ Errors ============

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', error='الصفحة غير موجودة'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', error='خطأ داخلي'), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
