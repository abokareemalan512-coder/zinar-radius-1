import requests
from routeros_api import RouterOsApiPool

# ================== إعدادات الميكروتيك ==================
MIKROTIK_HOST = '192.168.7.25'
MIKROTIK_USER = 'admin'
MIKROTIK_PASS = 'your_password'
MIKROTIK_PORT = 8728

# ================== إعدادات الموقع ==================
WEB_URL = 'https://zinar-net-radius.onrender.com/api/import_packages'
API_KEY = 'zinar-import-key-2026'  # ← نفس المفتاح الموجود في app.py

# ✅ قائمة الباقات التي تريد تجاهلها (الباقات الافتراضية للنظام)
EXCLUDED_PROFILES = ['default', 'default-encryption', 'netcut', 'profile1', 'profile2']

def fetch_and_send():
    print("🔄 جاري الاتصال بالميكروتيك...")
    try:
        pool = RouterOsApiPool(
            MIKROTIK_HOST,
            username=MIKROTIK_USER,
            password=MIKROTIK_PASS,
            port=MIKROTIK_PORT,
            plaintext_login=True
        )
        api = pool.get_api()
        
        print("📥 جاري سحب قائمة الباقات (PPP Profiles)...")
        profiles = api.get_binary_resource('/').call('ppp/profile/print')
        
        packages_data = []
        for p in profiles:
            profile_name = p.get('name', '').strip()
            
            # تخطي الباقات المستثناة
            if not profile_name or profile_name in EXCLUDED_PROFILES:
                print(f"⏭️ تم تخطي: {profile_name}")
                continue
            
            # قراءة السرعة من rate-limit
            rate_limit = p.get('rate-limit', '')
            speed = rate_limit if rate_limit else 'N/A'
            
            pkg_data = {
                'name': profile_name,
                'speed': speed,
                'price': 0,              # ستحدد السعر يدوياً في الموقع
                'duration': 30,          # 30 يوم افتراضي
                'duration_unit': 'days',
                'user_type': 'pppoe'
            }
            packages_data.append(pkg_data)
            print(f"   ✅ {profile_name} - السرعة: {speed}")
        
        pool.disconnect()
        print(f"\n✅ تم سحب {len(packages_data)} باقة من الميكروتيك.")
        
        if not packages_data:
            print("⚠️ لا توجد باقات للإرسال.")
            return

        print("\n📤 جاري إرسال البيانات إلى الموقع...")
        response = requests.post(
            WEB_URL,
            json=packages_data,
            headers={'X-API-Key': API_KEY},
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"🎉 نجاح! {result.get('message')}")
        elif response.status_code == 401:
            print("❌ فشل: مفتاح API غير صحيح.")
        else:
            print(f"❌ فشل الإرسال. رمز الحالة: {response.status_code}")
            print(f"التفاصيل: {response.text}")

    except Exception as e:
        print(f"❌ حدث خطأ: {e}")
        print("تأكد من أنك متصل بنفس شبكة الميكروتيك، وأن خدمة API مفعلة في IP -> Services.")

if __name__ == '__main__':
    fetch_and_send()
