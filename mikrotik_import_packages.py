# mikrotik_import_packages.py
"""
استيراد الباقات (Profiles) من MikroTik وإرسالها إلى موقع ZINAR

الاستخدام:
    # من متغيرات البيئة
    export MIKROTIK_HOST=192.168.7.25
    export MIKROTIK_USER=admin
    export MIKROTIK_PASS=secret
    python mikrotik_import_packages.py

    # أو من سطر الأوامر
    python mikrotik_import_packages.py --host 192.168.7.25 --user admin --pass secret

    # من عدة راوترات
    python mikrotik_import_packages.py --config routers.json

    # تعديل الأسعار دفعة واحدة
    python mikrotik_import_packages.py --host ... --price-map '{"1M":4,"2M":5}'

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


# ============ الإعدادات ============
WEB_URL = os.environ.get(
    'PACKAGES_URL',
    'https://zinar-net-radius.onrender.com/api/import_packages'
)
API_KEY = os.environ.get('IMPORT_API_KEY', 'zinar-import-key-2026')

DEFAULT_HOST = os.environ.get('MIKROTIK_HOST', '')
DEFAULT_USER = os.environ.get('MIKROTIK_USER', 'admin')
DEFAULT_PASS = os.environ.get('MIKROTIK_PASS', '')
DEFAULT_PORT = int(os.environ.get('MIKROTIK_PORT', 8728))

# الباقات المُستثناة (يُفصل بفاصلة)
_default_excluded = 'default,default-encryption,netcut,profile1,profile2'
EXCLUDED_PROFILES = set(
    p.strip() for p in os.environ.get('EXCLUDED_PROFILES', _default_excluded).split(',')
    if p.strip()
)

# المدة الافتراضية للباقة الجديدة
DEFAULT_DURATION = int(os.environ.get('DEFAULT_DURATION', 30))
DEFAULT_DURATION_UNIT = os.environ.get('DEFAULT_DURATION_UNIT', 'days')


# ============ الاتصال ============
def connect_mikrotik(host, user, password, port=DEFAULT_PORT, timeout=10):
    """فتح اتصال API"""
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
        logger.error(f"❌ خطأ: {e}")
        raise


# ============ استخراج الباقات ============
def fetch_ppp_profiles(api, price_map=None):
    """جلب PPP Profiles (باقات PPPoE)"""
    price_map = price_map or {}
    try:
        profiles = list(api.path('ppp', 'profile'))
        result = []
        skipped = 0

        for p in profiles:
            name = str(p.get('name', '')).strip()
            if not name:
                continue

            if name in EXCLUDED_PROFILES:
                logger.debug(f"⏭️ تخطي: {name}")
                skipped += 1
                continue

            rate_limit = str(p.get('rate-limit', '')).strip() or 'N/A'
            price = float(price_map.get(name, 0))

            result.append({
                'name': name,
                'speed': rate_limit,
                'price': price,
                'duration': DEFAULT_DURATION,
                'duration_unit': DEFAULT_DURATION_UNIT,
                'user_type': 'pppoe',
            })

        logger.info(f"📥 PPP Profiles: {len(result)} (تم تخطي {skipped})")
        return result
    except (TrapError, Exception) as e:
        logger.warning(f"⚠️ فشل جلب PPP Profiles: {e}")
        return []


def fetch_hotspot_profiles(api, price_map=None):
    """جلب Hotspot User Profiles"""
    price_map = price_map or {}
    try:
        profiles = list(api.path('ip', 'hotspot', 'user', 'profile'))
        result = []
        skipped = 0

        for p in profiles:
            name = str(p.get('name', '')).strip()
            if not name:
                continue

            if name in EXCLUDED_PROFILES:
                skipped += 1
                continue

            rate_limit = str(p.get('rate-limit', '')).strip() or 'N/A'
            price = float(price_map.get(name, 0))

            result.append({
                'name': name,
                'speed': rate_limit,
                'price': price,
                'duration': DEFAULT_DURATION,
                'duration_unit': DEFAULT_DURATION_UNIT,
                'user_type': 'hotspot',
            })

        logger.info(f"📥 Hotspot Profiles: {len(result)} (تم تخطي {skipped})")
        return result
    except (TrapError, Exception) as e:
        logger.warning(f"⚠️ فشل جلب Hotspot Profiles: {e}")
        return []


def fetch_all_packages(api, price_map=None, include_hotspot=True):
    """جلب كل الباقات"""
    ppp = fetch_ppp_profiles(api, price_map)
    hs = fetch_hotspot_profiles(api, price_map) if include_hotspot else []

    # دمج بدون تكرار (PPP له الأولوية)
    seen = set()
    merged = []
    for pkg in ppp + hs:
        key = (pkg['name'], pkg['user_type'])
        if key not in seen:
            seen.add(key)
            merged.append(pkg)

    return merged


# ============ الإرسال ============
def send_to_web(packages, web_url=WEB_URL, api_key=API_KEY):
    """إرسال الباقات إلى الموقع"""
    if not packages:
        logger.warning("⚠️ لا توجد باقات للإرسال")
        return False

    logger.info(f"📤 إرسال {len(packages)} باقة...")

    headers = {
        'X-API-Key': api_key,
        'Content-Type': 'application/json',
    }

    try:
        response = requests.post(
            web_url,
            json=packages,
            headers=headers,
            timeout=60,
        )

        if response.status_code == 200:
            result = response.json()
            logger.info(f"🎉 نجاح: {result.get('message', 'تم')}")
            logger.info(
                f"   جديدة: {result.get('imported', 0)} | "
                f"محدّثة: {result.get('updated', 0)} | "
                f"متجاهلة: {result.get('skipped', 0)}"
            )
            return True

        if response.status_code == 401:
            logger.error("❌ 401 — مفتاح API غير صحيح")
        else:
            logger.error(f"❌ فشل: رمز {response.status_code}")
            logger.error(f"   التفاصيل: {response.text[:500]}")
        return False

    except requests.exceptions.Timeout:
        logger.error("❌ انتهت المهلة")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ خطأ شبكة: {e}")
        return False


# ============ معالجة راوتر واحد ============
def process_router(host, user, password, port=DEFAULT_PORT,
                   include_hotspot=True, price_map=None):
    """معالجة راوتر واحد"""
    logger.info(f"{'='*50}")
    logger.info(f"🖥️  راوتر: {host}")
    logger.info(f"{'='*50}")

    api = None
    try:
        api = connect_mikrotik(host, user, password, port)
        packages = fetch_all_packages(api, price_map, include_hotspot)

        if not packages:
            logger.warning("⚠️ لا توجد باقات")
            return 0

        # عرض موجز
        for pkg in packages:
            logger.info(f"   📦 {pkg['name']:20s} ({pkg['user_type']:8s}) → {pkg['speed']}")

        ok = send_to_web(packages)
        return len(packages) if ok else 0

    except Exception as e:
        logger.error(f"❌ فشل {host}: {e}")
        return 0
    finally:
        if api:
            try:
                api.close()
            except Exception:
                pass


# ============ معالجة عدة راوترات ============
def process_multiple(config_file, price_map=None):
    """معالجة عدة راوترات من ملف JSON"""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.error(f"❌ ملف {config_file} غير موجود")
        return
    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON غير صالح: {e}")
        return

    # دعم التنسيقين: قائمة مباشرة أو كائن فيه routers و price_map
    if isinstance(config, dict):
        routers = config.get('routers', [])
        if price_map is None:
            price_map = config.get('price_map', {})
    else:
        routers = config

    if not isinstance(routers, list):
        logger.error("❌ يجب أن يحتوي على قائمة راوترات")
        return

    total = 0
    for r in routers:
        host = r.get('host', '')
        if not host:
            continue

        count = process_router(
            host=host,
            user=r.get('user', DEFAULT_USER),
            password=r.get('pass', ''),
            port=int(r.get('port', DEFAULT_PORT)),
            include_hotspot=r.get('include_hotspot', True),
            price_map=price_map,
        )
        total += count

    logger.info(f"{'='*50}")
    logger.info(f"📊 المجموع: {total} باقة من {len(routers)} راوتر")


# ============ CLI ============
def main():
    parser = argparse.ArgumentParser(
        description='استيراد الباقات من MikroTik إلى ZINAR'
    )
    parser.add_argument('--host', help='عنوان IP للراوتر')
    parser.add_argument('--user', default=DEFAULT_USER, help='اسم المستخدم')
    parser.add_argument('--pass', dest='password', help='كلمة المرور')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--web-url', default=WEB_URL)
    parser.add_argument('--api-key', default=API_KEY)
    parser.add_argument('--no-hotspot', action='store_true',
                        help='لا تجلب Hotspot Profiles')
    parser.add_argument('--config', help='ملف JSON لعدة راوترات')
    parser.add_argument('--price-map', help='JSON لخريطة الأسعار مثال: \'{"1M":4}\'')

    args = parser.parse_args()

    # تحديث الإعدادات
    global WEB_URL, API_KEY
    WEB_URL = args.web_url
    API_KEY = args.api_key

    # خريطة الأسعار
    price_map = None
    if args.price_map:
        try:
            price_map = json.loads(args.price_map)
            logger.info(f"💰 خريطة الأسعار: {price_map}")
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON الأسعار غير صالح: {e}")
            return

    # وضع متعدد
    if args.config:
        process_multiple(args.config, price_map)
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
        price_map=price_map,
    )


if __name__ == '__main__':
    main()
