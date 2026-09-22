# إضافة مشترك (يتم حفظه في المنصة وإضافته أوتوماتيكياً لكل السيرفرات عبر الـ API)
@app.route('/add_subscriber', methods=['GET', 'POST'])
def add_subscriber():
    db = get_db()
    cursor = db.cursor()
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        profile = request.form.get('profile', '').strip()
        service_type = request.form.get('service_type', 'hotspot').strip().lower()

        if not username or not password or not profile:
            flash('الرجاء إدخال كافة بيانات المشترك واختيار الباقة!', 'danger')
            return redirect(url_for('add_subscriber'))

        try:
            # 1. حفظ المشترك في قاعدة بيانات المنصة المركزية
            cursor.execute(
                'INSERT INTO subscribers (username, password, profile, service_type, status) VALUES (?, ?, ?, ?, ?)',
                (username, password, profile, service_type, 'active')
            )
            db.commit()

            # 2. جلب جميع السيرفرات المضافة في المنصة لإرسال الحساب إليها أوتوماتيكياً
            routers_list = cursor.execute('SELECT * FROM routers').fetchall()
            success_count = 0
            fail_routers = []

            for router in routers_list:
                api, connection, error = connect_mikrotik(
                    router['ip_address'],
                    router['username'],
                    router['password'],
                    router['port']
                )
                if api and not error:
                    try:
                        # هنا تم تصحيح التحقق ليعمل بشكل صحيح تماماً حسب نوع الخدمة
                        if service_type == 'hotspot':
                            users_resource = api.get_resource('/ip/hotspot/user')
                            existing = users_resource.get(name=username)
                            if not existing:
                                users_resource.add(name=username, password=password, profile=profile)
                        else:
                            secret_resource = api.get_resource('/ppp/secret')
                            existing = secret_resource.get(name=username)
                            if not existing:
                                secret_resource.add(name=username, password=password, profile=profile, service='pppoe')
                        
                        success_count += 1
                    except Exception as ex:
                        fail_routers.append(router['name'])
                    finally:
                        if connection:
                            try:
                                connection.disconnect()
                            except:
                                pass
                else:
                    fail_routers.append(router['name'])

            if fail_routers:
                flash(f'تمت إضافة المشترك في المنصة ونجح على ({success_count}) سيرفرات، ولكن تعذر الاتصال بـ: {", ".join(fail_routers)}', 'warning')
            else:
                flash(f'تمت إضافة المشترك ({username}) بنجاح وتعميمه أوتوماتيكياً على جميع السيرفرات المتاحة!', 'success')
                
            return redirect(url_for('subscribers'))

        except sqlite3.IntegrityError:
            flash('اسم المستخدم موجود بالفعل في المنصة، اختر اسماً آخر!', 'danger')
            return redirect(url_for('add_subscriber'))
        except Exception as e:
            flash(f"حدث خطأ أثناء حفظ المشترك: {str(e)}", "danger")
            return redirect(url_for('add_subscriber'))

    packages_list = cursor.execute('SELECT * FROM packages').fetchall()
    return render_template('add_subscriber.html', packages=packages_list)
