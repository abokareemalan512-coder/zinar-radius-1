class Router(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    ip_address = db.Column(db.String(50), nullable=False)
    username = db.Column(db.String(50), nullable=False)
    password = db.Column(db.String(50), nullable=True)
    port = db.Column(db.Integer, default=8728)

@app.route('/routers', methods=['GET', 'POST'])
def routers():
    if request.method == 'POST':
        name = request.form.get('name')
        ip_address = request.form.get('ip_address')
        username = request.form.get('username')
        password = request.form.get('password', '')
        port = request.form.get('port', 8728)
        if name and ip_address:
            try:
                new_router = Router(name=name, ip_address=ip_address, username=username, password=password, port=int(port))
                db.session.add(new_router)
                db.session.commit()
            except Exception:
                db.session.rollback()
        return redirect(url_for('routers'))
    
    routers_list = []
    try:
        routers_list = Router.query.all()
    except Exception:
        pass
    return render_template('routers.html', routers=routers_list)

@app.route('/delete_router/<int:id>')
def delete_router(id):
    try:
        router = Router.query.get_or_404(id)
        db.session.delete(router)
        db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(url_for('routers'))
