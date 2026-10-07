import requests
from routeros_api import RouterOsApiPool

# ================== إعدادات الميكروتيك ==================
MIKROTIK_HOST = '192.168.7.25'   # ضع IP الراوتر هنا (مثلاً 10.10.10.2 أو 198.145.118.146)
MIKROTIK_USER = 'admin'          # اسم مستخدم الميكروتيك
MIKROTIK_PASS = 'your_password'  # كلمة مرور الميكروتيك
MIKROTIK_PORT = 8728             # منفذ API الافتراضي (تأكد من تفعيله في IP -> Services)

# ================== إعدادات الموقع ==================
WEB_URL = 'https://zinar-net-radius.onrender.com/api/import_subscribers'

def fetch_and_send():
    print("🔄 جاري الاتصال بالميكروتيك...")
    try:
        # الاتصال بالميكروتيك
        pool = RouterOsApiPool(
            MIKROTIK_HOST, 
            username=MIKROTIK_USER, 
            password=MIKROTIK_PASS, 
            port=MIKROTIK_PORT, 
            plaintext_login=True
        )
        api = pool.get_api()
        
        print("📥 جاري سحب قائمة المشتركين (PPPoE Secrets)...")
        # جلب قائمة الـ PPP Secrets
        secrets = api.get_binary_resource('/').call('ppp/secret/print')
        
        subscribers_data = []
        for s in secrets:
            # تحويل الحالة من disabled إلى status
            is_disabled = s.get('disabled', 'false') == 'true'
            status = 'paused' if is_disabled else 'active'
            
            # استخراج الاسم من التعليق (comment) إذا وجد، وإلا استخدام اسم المستخدم
            comment = s.get('comment', '')
            name = comment if comment else s.get('name', '')
            
            sub_data = {
                'username': s.get('name', ''),
                'password': s.get('password', ''),
                'package': s.get('profile', ''),
                'user_type': 'pppoe',
                'status': status,
                'name': name
            }
            if sub_data['username']:
                subscribers_data.append(sub_data)
        
        pool.disconnect()
        print(f"✅ تم سحب {len(subscribers_data)} مشترك من الميكروتيك.")
        
        if not subscribers_data:
            print("⚠️ لا يوجد مشتركين للإرسال.")
            return

        # إرسال البيانات إلى الموقع
        print("📤 جاري إرسال البيانات إلى الموقع...")
        response = requests.post(WEB_URL, json=subscribers_data, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            print(f"🎉 نجاح! {result.get('message')}")
        else:
            print(f"❌ فشل الإرسال. رمز الحالة: {response.status_code}")
            print(f"التفاصيل: {response.text}")

    except Exception as e:
        print(f"❌ حدث خطأ: {e}")
        print("تأكد من أنك متصل بنفس شبكة الميكروتيك، وأن خدمة API مفعلة في IP -> Services.")

if __name__ == '__main__':
    fetch_and_send()
