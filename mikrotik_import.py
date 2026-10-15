# mikrotik_import.py
"""
سكربت استيراد المشتركين من MikroTik وإرسالهم إلى موقع ZINAR

الاستخدام:
    # من راوتر واحد (بيانات من المتغيرات)
    export MIKROTIK_HOST=192.168.7.25
    export MIKROTIK_USER=admin
    export MIKROTIK_PASS=secret
    python mikrotik_import.py

    # أو من سطر الأوامر
    python mikrotik_import.py --host 192.168.7.25 --user admin --pass secret

    # من عدة راوترات
    python mikrotik_import.py --config routers.json

المتطلبات:
    pip install librouteros requests
"""
import os
import sys
import json
import argparse
import logging

import requests

try:
    from librouteros import connect
    from librouteros.exceptions import TrapError, FatalError
except ImportError:
    print("❌ مكتبة librouteros غير مثبتة. نفّذ: pip install librouteros")
    sys.exit(1)

# ============ Logging ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============ الإعدادات (من البيئة) ============
WEB_URL = os.environ.get(
    'WEB_URL',
    'https://zinar-net-radius.onrender.com/api/import_subscribers'
)
API_KEY = os.environ.get('IMPORT_API_KEY', 'zinar-import-key-2026')

# قيم افتراضية للراوتر (تُستخدم إذا لم تُمرَّر)
DEFAULT_HOST = os.environ.get('MIKROTIK_HOST', '')
DEFAULT_USER = os.environ.get('MIKROTIK_USER', 'admin')
DEFAULT_PASS = os.environ.get('MIKROTIK_PASS', '')
DEFAULT_PORT = int(os.environ.get('MIKROTIK_PORT', 8728))
DEFAULT_TIMEOUT = int(os.environ.get('MIKROTIK_TIMEOUT', 10))


# ============ الاتصال بـ MikroTik ============
def connect_mikrotik(host, user, password, port=DEFAULT_PORT, timeout=DEFAULT_TIMEOUT):
    """فتح اتصال API مع MikroTik"""
    logger.info(f"🔄 الاتصال بـ {host}:{port}...")
    try:
        api = connect(
            username=user,
            password=password,
            host=host,
            port=port,
            timeout=timeout,
        )
        logger.info(f"✅ اتصال ناجح بـ {host}")
        return api
    except FatalError as e:
        logger.error(f"❌ فشل الاتصال: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ خطأ غير متوقع: {e}")
        raise


# ============ استخراج المشتركين ============
def fetch_pppoe_secrets(api):
    """جلب مستخدمي PPPoE"""
    try:
        secrets = list(api.path('ppp', 'secret'))
        result = []
        for s in secrets:
            username = str(s.get('name', '')).strip()
            if not username:
                continue

            disabled = str(s.get('disabled', 'false')).lower() in ('true', 'yes', '1')
            comment = str(s.get('comment', '')).strip()

            result.append({
                'username': username,
                'password': str(s.get('password', '')),
                'package': str(s.get('profile', '')),
                'user_type': 'pppoe',
                'status': 'paused' if disabled else 'active',
                'name': comment or username,
            })
        logger.info(f"📥 PPPoE: تم جلب {len(result)} مستخدم")
        return result
    except (TrapError, Exception) as e:
        logger.warning(f"⚠️ فشل جلب PPPoE: {e}")
        return []


def fetch_hotspot_users(api):
    """جلب مستخدمي Hotspot"""
    try:
        users = list(api.path('ip', 'hotspot', 'user'))
        result = []
        for u in users:
            username = str(u.get('name', '')).strip()
            if not username:
                continue

            disabled = str(u.get('disabled', 'false')).lower() in ('true', 'yes', '1')
            comment = str(u.get('comment', '')).strip()

            result.append({
                'username': username,
                'password': str(u.get('password', '')),
                'package': str(u.get('profile', '')),
                'user_type': 'hotspot',
                'status': 'paused' if disabled else 'active',
                'name': comment or username,
            })
        logger.info(f"📥 Hotspot: تم جلب {len(result)} مستخدم")
        return result
    except (TrapError, Exception) as e:
        logger.warning(f"⚠️ فشل جلب Hotspot: {e}")
        return []


def fetch_all_subscribers(api, include_hotspot=True):
    """جلب كل المشتركين من MikroTik"""
    pppoe = fetch_pppoe_secrets(api)
    hotspot = fetch_hotspot_users(api) if include_hotspot else []
    return pppoe + hotspot


# ============ الإرسال إلى الموقع ============
def send_to_web(subscribers, web_url=WEB_URL, api_key=API_KEY):
    """إرسال المشتركين إلى الموقع"""
    if not subscribers:
        logger.warning("⚠️ لا يوجد مشتركين للإرسال")
        return False

    logger.info(f"📤 إرسال {len(subscribers)} مشترك إلى الموقع...")

    headers = {
        'X-API-Key': api_key,
        'Content-Type': 'application/json',
    }

    try:
        response = requests.post(
            web_url,
            json=subscribers,
            headers=headers,
            timeout=90,
        )

        if response.status_code == 200:
            result = response.json()
            logger.info(f"🎉 نجاح: {result.get('message', 'تم الإرسال')}")
            logger.info(
                f"   جديد: {result.get('imported', 0)} | "
                f"محدّث: {result.get('updated', 0)} | "
                f"متجاهل: {result.get('skipped', 0)}"
            )
            return True

        if response.status_code == 401:
            logger.error("❌ 401 — مفتاح API غير صحيح. تحقق من IMPORT_API_KEY")
        else:
            logger.error(f"❌ فشل: رمز {response.status_code}")
            logger.error(f"   التفاصيل: {response.text[:500]}")
        return False

    except requests.exceptions.Timeout:
        logger.error("❌ انتهت مهلة الاتصال بالموقع")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ خطأ شبكة: {e}")
        return False


# ============ معالجة راوتر واحد ============
def process_router(host, user, password, port=DEFAULT_PORT, include_hotspot=True):
    """معالجة راوتر واحد: اتصال → جلب → إرسال"""
    logger.info(f"{'='*50}")
    logger.info(f"🖥️  راوتر: {host}")
    logger.info(f"{'='*50}")

    api = None
    try:
        api = connect_mikrotik(host, user, password, port)
        subscribers = fetch_all_subscribers(api, include_hotspot)

        if not subscribers:
            logger.warning("⚠️ لا يوجد مشتركين")
            return 0

        ok = send_to_web(subscribers)
        return len(subscribers) if ok else 0

    except Exception as e:
        logger.error(f"❌ فشل معالجة {host}: {e}")
        return 0
    finally:
        if api:
            try:
                api.close()
            except Exception:
                pass


# ============ معالجة عدة راوترات ============
def process_multiple(config_file):
    """معالجة عدة راوترات من ملف JSON"""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            routers = json.load(f)
    except FileNotFoundError:
        logger.error(f"❌ ملف {config_file} غير موجود")
        return
    except json.JSONDecodeError as e:
        logger.error(f"❌ خطأ في تحليل JSON: {e}")
        return

    if not isinstance(routers, list):
        logger.error("❌ الملف يجب أن يحتوي على قائمة راوترات")
        return

    total = 0
    for r in routers:
        host = r.get('host', '')
        if not host:
            logger.warning("⚠️ تجاهل راوتر بدون host")
            continue

        count = process_router(
            host=host,
            user=r.get('user', DEFAULT_USER),
            password=r.get('pass', ''),
            port=int(r.get('port', DEFAULT_PORT)),
            include_hotspot=r.get('include_hotspot', True),
        )
        total += count

    logger.info(f"{'='*50}")
    logger.info(f"📊 المجموع: {total} مشترك من {len(routers)} راوتر")


# ============ CLI ============
def main():
    parser = argparse.ArgumentParser(
        description='استيراد مشتركين من MikroTik إلى موقع ZINAR'
    )
    parser.add_argument('--host', help='عنوان IP لراوتر MikroTik')
    parser.add_argument('--user', default=DEFAULT_USER, help='اسم المستخدم')
    parser.add_argument('--pass', dest='password', help='كلمة المرور')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help='منفذ API')
    parser.add_argument('--web-url', default=WEB_URL, help='عنوان الموقع')
    parser.add_argument('--api-key', default=API_KEY, help='مفتاح API')
    parser.add_argument('--no-hotspot', action='store_true', help='لا تجلب Hotspot')
    parser.add_argument('--config', help='ملف JSON لعدة راوترات')

    args = parser.parse_args()

    # تحديث الإعدادات العامة
    global WEB_URL, API_KEY
    WEB_URL = args.web_url
    API_KEY = args.api_key

    # وضع متعدد الراوترات
    if args.config:
        process_multiple(args.config)
        return

    # وضع راوتر واحد
    host = args.host or DEFAULT_HOST
    password = args.password or DEFAULT_PASS

    if not host:
        parser.error("يجب تحديد --host أو MIKROTIK_HOST")
    if not password:
        parser.error("يجب تحديد --pass أو MIKROTIK_PASS")

    process_router(
        host=host,
        user=args.user,
        password=password,
        port=args.port,
        include_hotspot=not args.no_hotspot,
    )


if __name__ == '__main__':
    main()
