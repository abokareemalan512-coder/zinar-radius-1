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
    flash, jsonify, session, send_file
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import paramiko
import socket
from mikrotik_api import MikrotikAPI, MikrotikError, get_router_api, test_router_connection

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
    router_id = db.Column(db.Integer, db.ForeignKey('routers.id'))
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    first_used_at = db.Column(db.DateTime)
    pushed_at = db.Column(db.DateTime)
    pushed_router_id = db.Column(db.Integer)


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
            logger.error(traceback.format_exc())


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
                        ('pushed_at', "ALTER TABLE subscribers ADD COLUMN pushed_at TIMESTAMP"),
                        ('pushed_router_id', "ALTER TABLE subscribers ADD COLUMN pushed_router_id INTEGER"),
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


def test_mikrotik_connection(router):
    try:
        success, _ = test_router_connection(router)
        return success
    except Exception as e:
        logger.warning(f"⚠️ {router.name}: {e}")
        return False


def get_master_router():
    try:
        return Router.query.filter_by(is_master=True).first()
    except Exception:
        return None


def check_first_connections():
    try:
        pending = Subscriber.query.filter(
            Subscriber.expires_at.is_(None),
            Subscriber.pushed_router_id.isnot(None),
            Subscriber.status == 'active'
        ).count()

        if pending == 0:
            return 0

        routers = Router.query.filter_by(is_active=True).all()
        activated = 0
        now = datetime.utcnow()

        for router in routers:
            try:
                api = get_router_api(router)
                active_names = set()
                try:
                    for u in api.pppoe_active():
                        n = u.get('name') or u.get('user')
                        if n: active_names.add(n)
                except Exception: pass
                try:
                    for u in api.hotspot_active():
                        n = u.get('name') or u.get('user')
                        if n: active_names.add(n)
                except Exception: pass

                if not active_names: continue

                pending_subs = Subscriber.query.filter(
                    Subscriber.pushed_router_id == router.id,
                    Subscriber.expires_at.is_(None),
                    Subscriber.status == 'active',
                    Subscriber.username.in_(active_names)
                ).all()

                for sub in pending_subs:
                    pkg = Package.query.filter_by(name=sub.package).first() if sub.package else None
                    if pkg and pkg.duration:
                        sub.first_used_at = now
                        sub.expires_at = calculate_expiry(pkg, now)
                        activated += 1
            except Exception as e:
                logger.warning(f"⚠️ {router.name}: {e}")

        if activated > 0:
            db.session.commit()
        return activated
    except Exception as e:
        logger.warning(f"⚠️ check_first: {e}")
        return 0


# ============ Auth Guard ============

@app.before_request
def check_admin_login():
    if request.endpoint is None: return
    if request.endpoint.startswith('static'): return
    if request.endpoint in ('login', 'logout'): return
    if not session.get('admin_id'):
        return redirect(url_for('login'))


# ============ Auth Routes ============

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

@app.route('/dashboard')
def dashboard():
    try:
        try: check_first_connections()
        except Exception: pass

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

        preview = Subscriber.query.order_by(Subscriber.created_at.desc()).limit(8).all()

        return render_template(
            'dashboard.html',
            routers_count=routers_count, routers_online=routers_online,
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

        try: port = int(port)
        except ValueError: port = 22

        try:
            if is_master:
                Router.query.update({Router.is_master: False}, synchronize_session=False)
            r = Router(name=name, ip_address=ip, username=un, password=pw,
                       port=port, is_master=is_master, is_active=True)
            db.session.add(r)
            db.session.commit()
            ok = test_mikrotik_connection(r)
            flash(f'✅ الراوتر "{name}" أُضيف' if ok else '⚠️ أُضيف لكن الاتصال فشل',
                  'success' if ok else 'warning')
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


@app.route('/routers/toggle/<int:router_id>')
def toggle_router(router_id):
    try:
        router = Router.query.get_or_404(router_id)
        router.is_active = not router.is_active
        db.session.commit()

        pushed_subs = Subscriber.query.filter_by(pushed_router_id=router.id).all()
        success = fail = 0

        try:
            api = get_router_api(router)
            for sub in pushed_subs:
                ut = sub.user_type or 'pppoe'
                try:
                    if router.is_active:
                        if sub.status == 'active':
                            api.user_enable(sub.username, ut)
                        else:
                            api.user_disable(sub.username, ut)
                    else:
                        api.user_disable(sub.username, ut)
                        api.user_kick(sub.username, ut)
                    success += 1
                except MikrotikError:
                    fail += 1
        except MikrotikError as e:
            flash(f'⚠️ تحديث DB نجح لكن السيرفر فشل: {str(e)[:60]}', 'warning')
            return redirect(url_for('routers'))

        state = "▶ تشغيل" if router.is_active else "⏸ إيقاف"
        msg = f'✅ {state} "{router.name}"'
        if pushed_subs:
            msg += f' — {success} مشترك'
            if fail: msg += f' (فشل {fail})'
        flash(msg, 'success' if not fail else 'warning')
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


@app.route('/routers/test/<int:router_id>')
def test_router(router_id):
    try:
        r = Router.query.get_or_404(router_id)
        if test_mikrotik_connection(r):
            flash('✅ الاتصال ناجح', 'success')
        else:
            flash('⚠️ فشل الاتصال', 'warning')
    except Exception as e:
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('routers'))


@app.route('/routers/delete/<int:router_id>')
def delete_router(router_id):
    try:
        r = Router.query.get_or_404(router_id)
        db.session.delete(r)
        db.session.commit()
        flash('✅ تم الحذف', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('routers'))


@app.route('/routers/<int:router_id>/users')
def router_users(router_id):
    router = Router.query.get_or_404(router_id)
    ut = request.args.get('type', 'pppoe')
    users = []; actives = []; profiles = []; error = None
    try:
        api = get_router_api(router)
        if ut == 'hotspot':
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

    return render_template('router_users.html', router=router, users=users,
                           actives=actives, profiles=profiles, error=error,
                           user_type=ut)


@app.route('/routers/<int:router_id>/sync')
def sync_router(router_id):
    router = Router.query.get_or_404(router_id)
    ut = request.args.get('type', 'pppoe')

    try:
        api = get_router_api(router)
        if ut == 'hotspot':
            existing = {u.get('name') for u in api.hotspot_list() if u.get('name')}
        else:
            existing = {u.get('name') for u in api.pppoe_list() if u.get('name')}

        subs = Subscriber.query.filter_by(router_id=router_id, user_type=ut).all()
        created = skipped = failed = 0
        now = datetime.utcnow()

        for sub in subs:
            if sub.username in existing:
                skipped += 1
                sub.pushed_at = now
                sub.pushed_router_id = router_id
                continue
            try:
                api.user_create(sub.username, sub.password, ut,
                                profile=package_to_profile(sub.package))
                if sub.status != 'active':
                    api.user_disable(sub.username, ut)
                sub.pushed_at = now
                sub.pushed_router_id = router_id
                created += 1
            except MikrotikError as e:
                logger.warning(f"⚠️ {sub.username}: {e}")
                failed += 1

        db.session.commit()
        flash(f'✅ المزامنة: {created} جديد، {skipped} موجود، {failed} فشل',
              'success' if failed == 0 else 'warning')
    except MikrotikError as e:
        flash(f'❌ {e}', 'danger')

    return redirect(url_for('router_users', router_id=router_id, type=ut))


# ============ Import RSC ============

@app.route('/routers/<int:router_id>/import', methods=['GET', 'POST'])
def import_rsc(router_id):
    router = Router.query.get_or_404(router_id)
    if request.method == 'POST':
        f = request.files.get('rsc_file')
        push = request.form.get('push_to_router') == 'on'

        if not f or not f.filename:
            flash('❌ اختر ملف', 'danger')
            return redirect(url_for('import_rsc', router_id=router_id))
        if not f.filename.lower().endswith('.rsc'):
            flash('❌ يجب .rsc', 'danger')
            return redirect(url_for('import_rsc', router_id=router_id))

        try:
            content = f.read().decode('utf-8', errors='ignore')
            api = get_router_api(router)
            parsed = api.import_rsc_content(content)
        except Exception as e:
            flash(f'❌ {e}', 'danger')
            return redirect(url_for('import_rsc', router_id=router_id))

        all_users = []
        for u in parsed.get('pppoe', []):
            u['user_type'] = 'pppoe'; all_users.append(u)
        for u in parsed.get('hotspot', []):
            u['user_type'] = 'hotspot'; all_users.append(u)

        if not all_users:
            flash('⚠️ لا يوجد مستخدمون', 'warning')
            return redirect(url_for('import_rsc', router_id=router_id))

        added = skipped = pok = pf = 0
        for u in all_users:
            un = u.get('name')
            if not un: continue
            if Subscriber.query.filter_by(username=un, router_id=router_id).first():
                skipped += 1; continue
            try:
                s = Subscriber(
                    name=un, username=un, password=u.get('password', ''),
                    package=u.get('profile', ''), user_type=u.get('user_type', 'pppoe'),
                    router_id=router_id,
                    status='paused' if u.get('disabled') == 'true' else 'active'
                )
                db.session.add(s); added += 1
                if push:
                    try:
                        api.user_create(un, u.get('password', ''), u.get('user_type', 'pppoe'),
                                        profile=u.get('profile', 'default'))
                        pok += 1
                    except MikrotikError: pf += 1
            except Exception as e:
                logger.error(f"⚠️ {un}: {e}")

        db.session.commit()
        msg = f'✅ استيراد {added}'
        if skipped: msg += f' — تجاهل {skipped}'
        if push:
            msg += f' — رُفع {pok}'
            if pf: msg += f' — فشل {pf}'
        flash(msg, 'success' if not pf else 'warning')
        return redirect(url_for('subscribers'))

    return render_template('import_rsc.html', router=router)


# ============ Subscribers List ============

@app.route('/subscribers')
def subscribers():
    try: check_first_connections()
    except Exception: pass

    search = request.args.get('q', '').strip()
    ft = request.args.get('type', '').strip()
    fp = request.args.get('push', '').strip()
    now = datetime.utcnow()

    try:
        expired = Subscriber.query.filter(
            Subscriber.expires_at.isnot(None),
            Subscriber.expires_at < now,
            Subscriber.status == 'active'
        ).all()
        for s in expired:
            s.status = 'expired'
        if expired: db.session.commit()

        q = Subscriber.query
        if search:
            q = q.filter(db.or_(
                Subscriber.username.ilike(f'%{search}%'),
                Subscriber.name.ilike(f'%{search}%')
            ))
        if ft in ('pppoe', 'hotspot'):
            q = q.filter_by(user_type=ft)
        if fp == 'pushed':
            q = q.filter(Subscriber.pushed_at.isnot(None))
        elif fp == 'not_pushed':
            q = q.filter(Subscriber.pushed_at.is_(None))

        subs = q.order_by(Subscriber.created_at.desc()).all()
    except Exception as e:
        logger.error(f"❌ {e}")
        subs = []

    return render_template('subscribers.html',
        subscribers=subs,
        routers={r.id: r for r in Router.query.all()},
        packages=Package.query.order_by(Package.name).all(),
        search=search, now=now, filter_type=ft, filter_push=fp)


# ============ Add Subscriber ============

@app.route('/add-subscriber', methods=['GET', 'POST'])
@app.route('/subscribers/add', methods=['GET', 'POST'])
def add_subscriber():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        un = request.form.get('username', '').strip()
        pw = request.form.get('password', '').strip()
        pkg = request.form.get('package', '').strip()
        ut = request.form.get('user_type', 'pppoe').strip()
        rid = request.form.get('router_id', '').strip()

        if ut not in ('pppoe', 'hotspot'): ut = 'pppoe'
        if not un or not pw:
            flash('❌ الاسم وكلمة المرور مطلوبان', 'danger')
            return redirect(url_for('add_subscriber'))
        if Subscriber.query.filter_by(username=un).first():
            flash(f'❌ "{un}" موجود', 'danger')
            return redirect(url_for('add_subscriber'))

        try:
            s = Subscriber(
                name=name or un, username=un, password=pw,
                package=pkg, user_type=ut,
                router_id=int(rid) if rid else None,
                expires_at=None, status='active'
            )
            db.session.add(s)
            db.session.commit()
            flash(f'✅ "{un}" — 📌 في DB فقط (اضغط 📤 للرفع)', 'success')
            return redirect(url_for('subscribers'))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ {e}', 'danger')

    return render_template('add_subscriber.html',
        packages=Package.query.order_by(Package.name).all(),
        routers=Router.query.order_by(Router.name).all())


# ============ Bulk Add ============

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
        rid = request.form.get('router_id', '').strip()

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
        errors = []

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
                errors.append(f"{un}: مكرر"); failed += 1; continue
            try:
                s = Subscriber(name=un, username=un, password=pw,
                               package=pkg, user_type=ut,
                               router_id=int(rid) if rid else None,
                               expires_at=None, status='active')
                db.session.add(s)
                created += 1
            except Exception as e:
                failed += 1
                errors.append(f"{un}: {str(e)[:30]}")

        db.session.commit()
        msg = f'✅ {created} مشترك في DB'
        msg += ' — 📌 ارفعهم متى شئت'
        if failed: msg += f' — فشل {failed}'
        flash(msg, 'success' if not failed else 'warning')
        for e in errors[:5]: flash(f'⚠️ {e}', 'warning')

        return redirect(url_for('subscribers'))

    return render_template('bulk_add.html',
        packages=Package.query.order_by(Package.name).all(),
        routers=Router.query.order_by(Router.name).all())


# ============ Push Single ============

@app.route('/subscribers/push/<int:sub_id>')
def push_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        ut = sub.user_type or 'pppoe'

        if not sub.router_id:
            flash('⚠️ اختر راوتر أولًا', 'warning')
            return redirect(url_for('subscribers'))

        router = Router.query.get(sub.router_id)
        if not router:
            flash('❌ الراوتر غير موجود', 'danger')
            return redirect(url_for('subscribers'))

        try:
            api = get_router_api(router)
            check = (f'/ip hotspot user print where name="{sub.username}"' if ut == 'hotspot'
                     else f'/ppp secret print where name="{sub.username}"')
            exists = sub.username in api.execute(check)

            if exists:
                cmd = (f'/ip hotspot user set [find name="{sub.username}"] password="{sub.password}" profile="{package_to_profile(sub.package)}"'
                       if ut == 'hotspot' else
                       f'/ppp secret set [find name="{sub.username}"] password="{sub.password}" profile="{package_to_profile(sub.package)}"')
                api.execute(cmd)
                flash(f'✅ تم تحديث "{sub.username}"', 'success')
            else:
                api.user_create(sub.username, sub.password, ut,
                                profile=package_to_profile(sub.package))
                flash(f'✅ تم رفع "{sub.username}" إلى {router.name}', 'success')

            sub.pushed_at = datetime.utcnow()
            sub.pushed_router_id = router.id
            db.session.commit()
        except MikrotikError as e:
            flash(f'❌ {e}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


# ============ Move Subscriber ============

@app.route('/subscribers/move/<int:sub_id>', methods=['POST'])
def move_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        new_rid = request.form.get('new_router_id', '').strip()
        if not new_rid:
            flash('❌ اختر راوتر', 'danger')
            return redirect(url_for('subscribers'))

        new_rid = int(new_rid)
        new_router = Router.query.get(new_rid)
        if not new_router:
            flash('❌ الراوتر غير موجود', 'danger')
            return redirect(url_for('subscribers'))

        old_rid = sub.router_id
        ut = sub.user_type or 'pppoe'

        if old_rid and old_rid != new_rid:
            old = Router.query.get(old_rid)
            if old:
                try:
                    api_old = get_router_api(old)
                    api_old.user_kick(sub.username, ut)
                    api_old.user_delete(sub.username, ut)
                except MikrotikError:
                    pass

        msg = ''
        try:
            api_new = get_router_api(new_router)
            api_new.user_create(sub.username, sub.password, ut,
                                profile=package_to_profile(sub.package))
            sub.pushed_at = datetime.utcnow()
            sub.pushed_router_id = new_router.id
            msg = f' ✅ + {new_router.name}'
        except MikrotikError as e:
            msg = f' ⚠️ ({str(e)[:40]})'

        sub.router_id = new_rid
        sub.expires_at = None
        sub.first_used_at = None
        sub.status = 'active'

        db.session.commit()
        flash(f'🔀 نُقل "{sub.username}" إلى {new_router.name}{msg}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


# ============ Push Selected ============

@app.route('/subscribers/push-selected', methods=['POST'])
def push_selected():
    try:
        ids = request.form.get('ids', '').strip()
        rid = request.form.get('router_id', '').strip()
        if not ids or not rid:
            flash('❌ اختر راوتر ومشتركين', 'danger')
            return redirect(url_for('subscribers'))

        ids_list = [int(x) for x in ids.split(',') if x.strip().isdigit()]
        router = Router.query.get(int(rid))
        if not router:
            flash('❌ الراوتر غير موجود', 'danger')
            return redirect(url_for('subscribers'))

        try: api = get_router_api(router)
        except MikrotikError as e:
            flash(f'❌ {e}', 'danger')
            return redirect(url_for('subscribers'))

        subs = Subscriber.query.filter(Subscriber.id.in_(ids_list)).all()
        ok = fail = 0
        now = datetime.utcnow()

        for sub in subs:
            ut = sub.user_type or 'pppoe'
            try:
                api.user_create(sub.username, sub.password, ut,
                                profile=package_to_profile(sub.package))
                sub.pushed_at = now
                sub.pushed_router_id = router.id
                if not sub.router_id:
                    sub.router_id = router.id
                ok += 1
            except MikrotikError:
                fail += 1

        db.session.commit()
        flash(f'✅ رُفع {ok} إلى {router.name}' + (f' — فشل {fail}' if fail else ''),
              'success' if not fail else 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


# ============ Toggle / Reset / Extend ============

@app.route('/subscribers/toggle/<int:sub_id>')
def toggle_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        ut = sub.user_type or 'pppoe'
        if sub.status == 'active':
            sub.status = 'paused'
            if sub.pushed_router_id:
                r = Router.query.get(sub.pushed_router_id)
                if r:
                    try:
                        api = get_router_api(r)
                        api.user_disable(sub.username, ut)
                        api.user_kick(sub.username, ut)
                    except MikrotikError: pass
            flash(f'⏸ تم إيقاف "{sub.username}"', 'warning')
        else:
            if sub.expires_at and sub.expires_at < datetime.utcnow():
                flash('⚠️ منتهي', 'danger')
            else:
                sub.status = 'active'
                if sub.pushed_router_id:
                    r = Router.query.get(sub.pushed_router_id)
                    if r:
                        try:
                            api = get_router_api(r)
                            api.user_enable(sub.username, ut)
                        except MikrotikError: pass
                flash(f'▶ تم تفعيل "{sub.username}"', 'success')
        db.session.commit()
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
        ut = sub.user_type or 'pppoe'
        if sub.pushed_router_id:
            r = Router.query.get(sub.pushed_router_id)
            if r:
                try:
                    api = get_router_api(r)
                    api.user_enable(sub.username, ut)
                    api.user_kick(sub.username, ut)
                except MikrotikError: pass
        db.session.commit()
        flash('🔄 تم التصفير — ⏳ يبدأ من أول اتصال', 'success')
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
        old_pw = sub.password
        old_pkg = sub.package
        old_un = sub.username

        sub.name = request.form.get('name', '').strip() or sub.name
        nun = request.form.get('username', '').strip()
        if nun: sub.username = nun
        pw = request.form.get('password', '').strip()
        if pw: sub.password = pw

        pkg = request.form.get('package', '').strip()
        if pkg and pkg != sub.package:
            sub.package = pkg

        rid = request.form.get('router_id', '').strip()
        sub.router_id = int(rid) if rid else None

        if sub.pushed_router_id:
            r = Router.query.get(sub.pushed_router_id)
            if r:
                ut = sub.user_type or 'pppoe'
                try:
                    api = get_router_api(r)
                    if pw and pw != old_pw:
                        api.user_update_password(sub.username, pw, ut)
                    if pkg and pkg != old_pkg:
                        api.user_update_profile(sub.username, package_to_profile(pkg), ut)
                        api.user_kick(sub.username, ut)
                    if nun and nun != old_un:
                        api.user_delete(old_un, ut)
                        api.user_create(nun, pw or old_pw, ut,
                                        profile=package_to_profile(pkg or old_pkg))
                except MikrotikError: pass

        db.session.commit()
        flash('✅ تم التحديث', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


# ============ Delete Single ============

@app.route('/subscribers/delete/<int:sub_id>')
def delete_subscriber(sub_id):
    try:
        sub = Subscriber.query.get_or_404(sub_id)
        if sub.pushed_router_id:
            r = Router.query.get(sub.pushed_router_id)
            if r:
                ut = sub.user_type or 'pppoe'
                try:
                    api = get_router_api(r)
                    api.user_kick(sub.username, ut)
                    api.user_delete(sub.username, ut)
                except MikrotikError: pass
        db.session.delete(sub)
        db.session.commit()
        flash('✅ تم الحذف', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ {str(e)}', 'danger')
    return redirect(url_for('subscribers'))


# ============ Delete Bulk ============

@app.route('/subscribers/bulk-delete', methods=['POST'])
def bulk_delete_subscribers():
    """حذف مجموعة مختارة من المشتركين"""
    try:
        ids = request.form.get('ids', '').strip()
        if not ids:
            flash('❌ لم تحدد أي مشترك', 'warning')
            return redirect(url_for('subscribers'))

        ids_list = [int(x) for x in ids.split(',') if x.strip().isdigit()]
        if not ids_list:
            flash('❌ معرّفات غير صالحة', 'danger')
            return redirect(url_for('subscribers'))

        subs = Subscriber.query.filter(Subscriber.id.in_(ids_list)).all()
        deleted = 0
        router_fail = 0
        errors = []

        for sub in subs:
            if sub.pushed_router_id:
                r = Router.query.get(sub.pushed_router_id)
                if r:
                    ut = sub.user_type or 'pppoe'
                    try:
                        api = get_router_api(r)
                        api.user_kick(sub.username, ut)
                        api.user_delete(sub.username, ut)
                    except Exception as e:
                        router_fail += 1
                        errors.append(f"{sub.username}: {str(e)[:30]}")

            db.session.delete(sub)
            deleted += 1

        db.session.commit()

        msg = f'🗑 تم حذف {deleted} مشترك'
        if router_fail:
            msg += f' — فشل إزالة {router_fail} من السيرفر'
        flash(msg, 'success' if not router_fail else 'warning')
        for e in errors[:5]:
            flash(f'⚠️ {e}', 'warning')

    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ bulk_delete: {e}")
        flash(f'❌ {str(e)}', 'danger')

    return redirect(url_for('subscribers'))


# ============ Delete Expired ============

@app.route('/subscribers/delete-expired', methods=['POST'])
def delete_expired_subscribers():
    """حذف كل المشتركين المنتهية صلاحيتهم"""
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
        unique_expired = []
        for s in all_expired:
            if s.id not in seen:
                seen.add(s.id)
                unique_expired.append(s)

        if not unique_expired:
            flash('ℹ️ لا يوجد مشتركون منتهون', 'info')
            return redirect(url_for('subscribers'))

        deleted = 0
        router_fail = 0

        for sub in unique_expired:
            if sub.pushed_router_id:
                r = Router.query.get(sub.pushed_router_id)
                if r:
                    ut = sub.user_type or 'pppoe'
                    try:
                        api = get_router_api(r)
                        api.user_kick(sub.username, ut)
                        api.user_delete(sub.username, ut)
                    except Exception:
                        router_fail += 1

            db.session.delete(sub)
            deleted += 1

        db.session.commit()

        msg = f'🗑 تم حذف {deleted} مشترك منتهي'
        if router_fail:
            msg += f' — فشل إزالة {router_fail} من السيرفر'
        flash(msg, 'success' if not router_fail else 'warning')

    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ delete_expired: {e}")
        flash(f'❌ {str(e)}', 'danger')

    return redirect(url_for('subscribers'))


# ============ Export ============

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


# ============ Run ============

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
