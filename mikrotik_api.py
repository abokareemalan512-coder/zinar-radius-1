"""
mikrotik_api.py
وحدة مسؤولة عن الاتصال بأجهزة MikroTik (RouterOS API) والتعامل معها.
مصممة للعمل مع عدة راوترات في نفس الوقت - كل استدعاء بياخد كائن Router
(فيه ip_address, username, password) ويتصل فيه بشكل مستقل.
"""

import socket
import routeros_api

# مهلة الاتصال بالثواني - إذا الراوتر مش قادر يوصل، ما منستنى أكتر من هيك
CONNECTION_TIMEOUT = 5


def _connect(router, port=None, use_ssl=False):
    """
    يفتح اتصال جديد براوتر واحد ويرجع كائن API جاهز للاستخدام.
    لازم تستدعي .disconnect() على الـ connection بعد ما تخلص (أو استخدم try/finally).
    """
    if port is None:
        port = getattr(router, 'port', None) or 8728

    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(CONNECTION_TIMEOUT)
    try:
        connection = routeros_api.RouterOsApiPool(
            host=router.ip_address,
            username=router.username,
            password=router.password,
            port=port,
            use_ssl=use_ssl,
            ssl_verify=False,
            plaintext_login=True,
        )
        api = connection.get_api()
        return connection, api
    finally:
        socket.setdefaulttimeout(old_timeout)


def test_connection(router):
    """
    يتأكد فقط إنه الراوتر قابل للوصول والبيانات صحيحة.
    يرجع dict فيه success (True/False) ورسالة، وما بيرمي استثناء أبداً
    (مهم عشان صفحة الراوترات ما تطيح لو راوتر واحد وقع).
    """
    connection = None
    try:
        connection, api = _connect(router)
        identity = api.get_resource('/system/identity').get()
        name = identity[0].get('name', 'MikroTik') if identity else 'MikroTik'
        return {'success': True, 'message': f'متصل - {name}'}
    except Exception as e:
        return {'success': False, 'message': str(e)}
    finally:
        if connection:
            try:
                connection.disconnect()
            except Exception:
                pass


def get_router_stats(router):
    """
    يرجع إحصائيات حية من راوتر واحد: عدد جلسات PPPoE النشطة،
    عدد جلسات Hotspot النشطة، ونسبة استخدام المعالج.
    عند أي خطأ (راوتر مقطوع، بيانات غلط...) بيرجع أصفار بدل ما يوقّع الموقع.
    """
    result = {
        'online': False,
        'ppp_active': 0,
        'hotspot_active': 0,
        'cpu_load': 0,
        'uptime': '-',
        'error': None,
    }
    connection = None
    try:
        connection, api = _connect(router)

        # جلسات PPPoE النشطة
        try:
            ppp_active = api.get_resource('/ppp/active').get()
            result['ppp_active'] = len(ppp_active)
        except Exception:
            pass

        # جلسات Hotspot النشطة
        try:
            hotspot_active = api.get_resource('/ip/hotspot/active').get()
            result['hotspot_active'] = len(hotspot_active)
        except Exception:
            pass

        # حمل المعالج والوقت التشغيلي
        try:
            resource = api.get_resource('/system/resource').get()
            if resource:
                result['cpu_load'] = resource[0].get('cpu-load', 0)
                result['uptime'] = resource[0].get('uptime', '-')
        except Exception:
            pass

        result['online'] = True
    except Exception as e:
        result['error'] = str(e)
    finally:
        if connection:
            try:
                connection.disconnect()
            except Exception:
                pass
    return result


def get_all_routers_stats(routers):
    """
    ياخد لستة من كائنات Router (من قاعدة البيانات) ويرجع إحصائيات
    كل واحد فيهم + المجموع الكلي. هاي الدالة يلي منستخدمها بالداشبورد
    لجمع بيانات كل الراوترات مع بعض.
    """
    per_router = []
    totals = {'ppp_active': 0, 'hotspot_active': 0, 'online_count': 0}

    for router in routers:
        stats = get_router_stats(router)
        stats['router_id'] = router.id
        stats['router_name'] = router.name
        per_router.append(stats)

        if stats['online']:
            totals['online_count'] += 1
            totals['ppp_active'] += stats['ppp_active']
            totals['hotspot_active'] += stats['hotspot_active']

    return {'per_router': per_router, 'totals': totals}


def get_userman_users(router):
    """
    يجرب يقرأ مستخدمي User Manager عبر RouterOS API (مش عبر Terminal).
    بيرجع dict فيه success/error والبيانات الخام، مفيدة للتشخيص ولإعادة الاستخدام لاحقاً.
    """
    connection = None
    try:
        connection, api = _connect(router)
        users = api.get_resource('/tool/user-manager/user').get()
        return {'success': True, 'count': len(users), 'raw': users}
    except Exception as e:
        return {'success': False, 'error': str(e)}
    finally:
        if connection:
            try:
                connection.disconnect()
            except Exception:
                pass


def get_userman_profiles(router):
    """نفس الفكرة بس للبروفايلات (الباقات) المعرّفة بـ User Manager."""
    connection = None
    try:
        connection, api = _connect(router)
        profiles = api.get_resource('/tool/user-manager/profile').get()
        return {'success': True, 'count': len(profiles), 'raw': profiles}
    except Exception as e:
        return {'success': False, 'error': str(e)}
    finally:
        if connection:
            try:
                connection.disconnect()
            except Exception:
                pass


def add_userman_user(router, username, password, profile=None):
    """
    يضيف مستخدم جديد لـ User Manager مباشرة عبر API.
    profile اختياري - إذا انحط، بينربط المستخدم بباقة معينة مباشرة.
    """
    connection = None
    try:
        connection, api = _connect(router)
        params = {'customer': 'admin', 'username': username, 'password': password}
        if profile:
            params['actual-profile'] = profile
        api.get_resource('/tool/user-manager/user').add(**params)
        return {'success': True}
    except Exception as e:
        return {'success': False, 'error': str(e)}
    finally:
        if connection:
            try:
                connection.disconnect()
            except Exception:
                pass
    """
    يفصل مستخدم PPPoE معيّن فوراً من راوتر محدد (متل زر "قطع الاتصال").
    """
    connection = None
    try:
        connection, api = _connect(router)
        active = api.get_resource('/ppp/active')
        sessions = active.get(name=username)
        for session in sessions:
            active.remove(id=session['id'])
        return {'success': True}
    except Exception as e:
        return {'success': False, 'message': str(e)}
    finally:
        if connection:
            try:
                connection.disconnect()
            except Exception:
                pass
