"""
config.py — إعدادات النظام
يُقرأ من Environment Variables مع قيم افتراضية آمنة
"""
import os
import logging

logger = logging.getLogger(__name__)


def _get_bool(key, default=False):
    """قراءة قيمة boolean من البيئة"""
    val = os.environ.get(key, str(default)).lower()
    return val in ('true', '1', 'yes', 'on')


def _get_int(key, default=0):
    """قراءة قيمة integer من البيئة"""
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def _get_float(key, default=0.0):
    """قراءة قيمة float من البيئة"""
    try:
        return float(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


# ============ Sham Cash (الدفع) ============
SHAM_CASH_ACCOUNT = os.environ.get('SHAM_CASH_ACCOUNT', '5889')
SHAM_CASH_ENABLED = _get_bool('SHAM_CASH_ENABLED', True)
PAYMENT_MODE = os.environ.get('PAYMENT_MODE', 'auto')  # auto | manual
PLATFORM_SHAMCASH_ADDRESS = os.environ.get('PLATFORM_SHAMCASH_ADDRESS', '5889')

# ============ API Syria (اختياري) ============
API_SYRIA_BASE_URL = os.environ.get('API_SYRIA_BASE_URL', '')
API_SYRIA_KEY = os.environ.get('API_SYRIA_KEY', '')
AUTO_VERIFY_ENABLED = _get_bool('AUTO_VERIFY_ENABLED', False)  # افتراضيًا معطّل
MIN_TX_LENGTH = _get_int('MIN_TX_LENGTH', 6)

# ============ أسعار الباقات (Fallback فقط) ============
# المصدر الأساسي هو جدول packages في قاعدة البيانات
# هذا يُستخدم فقط إذا لم يوجد سعر في الجدول
PACKAGES_PRICES = {
    "1M":  _get_float('PRICE_1M', 4),
    "2M":  _get_float('PRICE_2M', 5),
    "4M":  _get_float('PRICE_4M', 7),
    "8M":  _get_float('PRICE_8M', 10),
}


# ============ تحقق من الإعدادات الحساسة ============
def validate_config():
    """التحقق من صحة الإعدادات عند بدء التشغيل"""
    warnings = []

    if SHAM_CASH_ENABLED and not SHAM_CASH_ACCOUNT:
        warnings.append("⚠️ Sham Cash مُفعّل لكن الحساب فارغ")

    if AUTO_VERIFY_ENABLED and not API_SYRIA_BASE_URL:
        warnings.append("⚠️ التحقق التلقائي مُفعّل لكن API Syria فارغ")
        logger.warning("AUTO_VERIFY مُعطّل تلقائيًا بسبب نقص إعدادات API")

    if PAYMENT_MODE not in ('auto', 'manual'):
        warnings.append(f"⚠️ PAYMENT_MODE غير صحيح: {PAYMENT_MODE}")

    for w in warnings:
        logger.warning(w)

    return len(warnings) == 0


# يُنفّذ عند الاستيراد
validate_config()
