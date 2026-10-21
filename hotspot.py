# hotspot.py
"""
صفحة دخول Hotspot — توجّه المستخدم إلى صفحة تسجيل الدخول في MikroTik
"""
import os
import re
import html
import logging
import urllib.parse

from flask import Blueprint, request, redirect, render_template_string

logger = logging.getLogger(__name__)

hotspot_bp = Blueprint('hotspot', __name__)

# ============ الإعدادات ============
# يمكن تغيير العنوان من Environment Variables
DEFAULT_LOGIN_URL = os.environ.get('HOTSPOT_LOGIN_URL', 'http://13.13.13.13/login')

# النطاقات المسموح بها في link_login (لمنع Open Redirect)
ALLOWED_HOSTS = set(
    h.strip() for h in os.environ.get(
        'HOTSPOT_ALLOWED_HOSTS',
        '13.13.13.13,10.5.50.1,192.168.88.1,localhost,127.0.0.1'
    ).split(',') if h.strip()
)

# صيغة الكود المسموح (أرقام وحروف إنجليزية، 4-32 حرفًا)
CODE_PATTERN = re.compile(r'^[A-Za-z0-9\-_]{4,32}$')

# ============ صفحة الدخول ============
LOGIN_PAGE = """<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>شبكة زينار نت — تسجيل الدخول</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Tahoma, sans-serif;
            background: linear-gradient(135deg, #e0f2fe 0%, #f0f9ff 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0;
            padding: 20px;
        }
        .card {
            background: #fff;
            max-width: 380px;
            width: 100%;
            padding: 30px;
            border-radius: 18px;
            box-shadow: 0 10px 40px rgba(0, 100, 200, 0.15);
        }
        h2 {
            color: #0284c7;
            text-align: center;
            margin: 0 0 8px;
            font-size: 24px;
        }
        .mac {
            text-align: center;
            color: #94a3b8;
            font-size: 11px;
            font-family: monospace;
            margin-bottom: 20px;
            direction: ltr;
            min-height: 14px;
        }
        .input {
            width: 100%;
            padding: 14px;
            border: 2px solid #e2e8f0;
            border-radius: 10px;
            text-align: center;
            font-size: 17px;
            font-family: monospace;
            letter-spacing: 1px;
            outline: none;
            transition: border-color 0.2s;
        }
        .input:focus { border-color: #0ea5e9; }
        .btn {
            width: 100%;
            padding: 14px;
            margin-top: 14px;
            background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
            color: #fff;
            border: none;
            border-radius: 10px;
            font-size: 17px;
            font-weight: bold;
            cursor: pointer;
            transition: transform 0.15s, box-shadow 0.15s;
        }
        .btn:hover { transform: translateY(-1px); box-shadow: 0 6px 20px rgba(2, 132, 199, 0.35); }
        .btn:active { transform: translateY(0); }
        .error {
            background: #fee2e2;
            color: #b91c1c;
            padding: 12px;
            border-radius: 10px;
            text-align: center;
            margin-bottom: 16px;
            font-size: 14px;
        }
        .footer {
            text-align: center;
            font-size: 11px;
            color: #94a3b8;
            margin-top: 22px;
            padding-top: 16px;
            border-top: 1px solid #f1f5f9;
        }
    </style>
</head>
<body>
    <div class="card">
        <h2>شبكة زينار نت</h2>
        <p class="mac">{{ mac }}</p>

        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}

        <form method="post" autocomplete="off">
            <input type="hidden" name="link_login" value="{{ link_login }}">
            <input
                name="code"
                class="input"
                placeholder="أدخل كود الكرت"
                pattern="[A-Za-z0-9\\-_]{4,32}"
                maxlength="32"
                autofocus
                required
            >
            <button class="btn" type="submit">اتصال</button>
        </form>

        <p class="footer">للدعم الفني تواصل مع الإدارة</p>
    </div>
</body>
</html>
"""


# ============ Helpers ============

def _is_allowed_login_url(url):
    """تحقق أن link_login يخص نطاقًا مسموحًا به"""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        hostname = (parsed.hostname or '').lower()
        if not hostname:
            return False
        # إذا لم تُعرّف قائمة، اسمح بالجميع
        if not ALLOWED_HOSTS:
            return True
        return hostname in ALLOWED_HOSTS
    except Exception:
        return False


def _sanitize_login_url(raw):
    """تحقق وأعد link_login آمنًا"""
    if not raw:
        return DEFAULT_LOGIN_URL
    decoded = urllib.parse.unquote(raw)
    if _is_allowed_login_url(decoded):
        return decoded
    logger.warning(f"⚠️ link_login غير مسموح: {decoded}")
    return DEFAULT_LOGIN_URL


def _extract_client_mac(req):
    """استخراج MAC من الطلب (MikroTik يمرره كـ param)"""
    mac = req.args.get('mac', '') or req.form.get('mac', '')
    mac = mac.strip().upper()
    # تحقق من صيغة MAC
    if re.match(r'^([0-9A-F]{2}:){5}[0-9A-F]{2}$', mac):
        return mac
    return ''


# ============ Routes ============

@hotspot_bp.route('/hotspot/login', methods=['GET', 'POST'])
def hotspot_login():
    """
    صفحة الدخول:
    - GET: تعرض النموذج
    - POST: تُعيد توجيه المستخدم إلى صفحة MikroTik
    """
    mac = _extract_client_mac(request)
    link_login = _sanitize_login_url(
        request.args.get('link-login', '') or request.form.get('link_login', '')
    )

    error = None

    if request.method == 'POST':
        code = request.form.get('code', '').strip()

        if not code:
            error = 'الرجاء كتابة الكود'
            logger.info(f"Hotspot: كود فارغ من MAC={mac or 'unknown'}")

        elif not CODE_PATTERN.match(code):
            error = 'صيغة الكود غير صحيحة'
            logger.warning(f"Hotspot: كود غير صالح '{code}' من MAC={mac or 'unknown'}")

        else:
            # إعادة التوجيه إلى MikroTik
            login_url = (
                f"{link_login}"
                f"?username={urllib.parse.quote(code)}"
                f"&password={urllib.parse.quote(code)}"
            )
            logger.info(f"Hotspot: توجيه '{code}' من MAC={mac or 'unknown'}")
            return redirect(login_url, code=302)

    # عرض الصفحة
    return render_template_string(
        LOGIN_PAGE,
        mac=html.escape(mac) if mac else '',
        link_login=html.escape(link_login),
        error=html.escape(error) if error else None,
    )
