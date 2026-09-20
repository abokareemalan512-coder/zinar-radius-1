from datetime import datetime
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_sqlalchemy import SQLAlchemy
from mikrotik_api import MikroTikAPI

app = Flask(__name__)
app.config['SECRET_KEY'] = 'zinar_secret_key_2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///zinar.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# جداول قاعدة البيانات الحقيقية
class Router(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  name = db.Column(db.String(100), nullable=False)
  ip = db.Column(db.String(100), nullable=False)
  username = db.Column(db.String(100), nullable=False)
  password = db.Column(db.String(100), nullable=False)
  port = db.Column(db.Integer, default=8728)


class Subscriber(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  username = db.Column(db.String(100), unique=True, nullable=False)
  password = db.Column(db.String(100), nullable=False)
  profile = db.Column(db.String(100), nullable=False)
  phone = db.Column(db.String(50))
  expiry_date = db.Column(db.String(50))
  status = db.Column(db.String(20), default='active')  # active / expired
  router_id = db.Column(db.Integer, db.ForeignKey('router.id'))


with app.app_context():
  db.create_all()


@app.route('/')
def dashboard():
  routers_count = Router.query.count()
  sub_count = Subscriber.query.count()
  active_subs = Subscriber.query.filter_by(status='active').count()
  subscribers = Subscriber.query.all()
  return render_template(
      'dashboard.html',
      routers_count=routers_count,
      sub_count=sub_count,
      active_subs=active_subs,
      subscribers=subscribers,
  )


@app.route('/routers', methods=['GET', 'POST'])
def routers():
  if request.method == 'POST':
    name = request.form.get('name')
    ip = request.form.get('ip')
    username = request.form.get('username')
    password = request.form.get('password')
    port = int(request.form.get('port', 8728))

    new_router = Router(
        name=name, ip=ip, username=username, password=password, port=port
    )
    db.session.add(new_router)
    db.session.commit()
    flash('تم إضافة الراوتر بنجاح!', 'success')
    return redirect(url_for('routers'))

  all_routers = Router.query.all()
  return render_template('routers.html', routers=all_routers)


@app.route('/subscribers')
def subscribers():
  all_subs = Subscriber.query.all()
  return render_template('subscribers.html', subscribers=all_subs)


@app.route('/add_subscriber', methods=['GET', 'POST'])
def add_subscriber():
  all_routers = Router.query.all()
  if request.method == 'POST':
    username = request.form.get('username')
    password = request.form.get('password')
    profile = request.form.get('profile')
    phone = request.form.get('phone')
    expiry = request.form.get('expiry_date')
    router_id = request.form.get('router_id')

    # إضافة المشترك في قاعدة البيانات المحلية
    new_sub = Subscriber(
        username=username,
        password=password,
        profile=profile,
        phone=phone,
        expiry_date=expiry,
        router_id=router_id,
    )
    db.session.add(new_sub)
    db.session.commit()

    # محاولة إرسال البيانات لسيرفر الميكروتيك الحقيقي عبر الـ API
    router = Router.query.get(router_id)
    if router:
      mk = MikroTikAPI(router.ip, router.username, router.password, router.port)
      if mk.connect():
        mk.add_hotspot_user(username, password, profile)
        flash(
            'تم إضافة المشترك في قاعدة البيانات وتفعيله على الميكروتيك بنجاح!',
            'success',
        )
      else:
        flash(
            'تم الحفظ محلياً، ولكن تعذر الاتصال بسيرفر الميكروتيك!',
            'warning',
        )

    return redirect(url_for('dashboard'))

  return render_template('add_subscriber.html', routers=all_routers)


@app.route('/delete_subscriber/<int:id>')
def delete_subscriber(id):
  sub = Subscriber.query.get_or_404(id)
  db.session.delete(sub)
  db.session.commit()
  flash('تم حذف المشترك بنجاح.', 'success')
  return redirect(url_for('dashboard'))


@app.route('/packages')
def packages():
  return render_template(
      'packages.html'
  )  # صفحة الباقات والسرعات المرتبطة بالميكروتيك


@app.route('/sessions')
def sessions():
  return render_template(
      'sessions.html'
  )  # صفحة الجلسات النشطة الحية من الراوتر


@app.route('/payments')
def payments():
  return render_template('payments.html')  # صفحة المدفوعات والتقارير المالية


if __name__ == '__main__':
  app.run(host='0.0.0.0', port=5000, debug=True)
