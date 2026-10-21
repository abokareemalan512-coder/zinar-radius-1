// admin_settings.js

(function () {
    'use strict';

    // ==========================================
    // عرض/إخفاء التوكن
    // ==========================================
    function initTokenToggle() {
        const btn = document.getElementById('toggleTokenBtn');
        const input = document.getElementById('input_token');
        const icon = document.getElementById('toggleTokenIcon');
        if (!btn || !input || !icon) return;

        btn.addEventListener('click', function () {
            if (input.type === 'password') {
                input.type = 'text';
                icon.className = 'bi bi-eye-slash';
            } else {
                input.type = 'password';
                icon.className = 'bi bi-eye';
            }
        });
    }

    // ==========================================
    // اختبار التلجرام
    // ==========================================
    function initTestButton() {
        const btn = document.getElementById('testTelegramBtn');
        if (!btn) return;

        btn.addEventListener('click', async function () {
            const originalHTML = this.innerHTML;
            this.disabled = true;
            this.innerHTML = '<span class="spinner-border spinner-border-sm"></span> جاري الإرسال...';

            try {
                const res = await fetch('/admin-settings/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                });
                const data = await res.json();

                if (data.success) {
                    alert('✅ تم إرسال رسالة الاختبار بنجاح!\n\nتحقق من Telegram.');
                    // تحديث السجل بعد 2 ثانية
                    setTimeout(fetchTelegramData, 2000);
                } else {
                    alert('❌ فشل الإرسال: ' + (data.error || 'خطأ غير معروف'));
                }
            } catch (err) {
                alert('❌ خطأ في الاتصال: ' + err.message);
            } finally {
                this.disabled = false;
                this.innerHTML = originalHTML;
            }
        });
    }

    // ==========================================
    // خريطة أنواع الرسائل
    // ==========================================
    const TYPE_LABELS = {
        'new_subscriber': 'مشترك جديد',
        'expired_subscriber': 'اشتراك منتهي',
        'bulk_add': 'إضافة جماعية',
        'admin_action': 'إجراء إداري',
        'router_status': 'حالة راوتر',
        'router_alert': 'تنبيه راوتر',
        'expiry_reminder': 'تذكير انتهاء',
        'incoming': 'رسالة واردة',
        'incoming_group': 'رسالة مجموعة',
        'test': 'اختبار',
        'reply': 'رد',
    };

    // ==========================================
    // أمان: تنظيف HTML
    // ==========================================
    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str).replace(/[&<>"']/g, function (m) {
            return {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;',
            }[m];
        });
    }

    // ==========================================
    // جلب بيانات التلجرام
    // ==========================================
    let lastFetch = 0;
    const MIN_INTERVAL = 3000; // منع الاستدعاء المتكرر

    async function fetchTelegramData() {
        const now = Date.now();
        if (now - lastFetch < MIN_INTERVAL) return;
        lastFetch = now;

        try {
            const res = await fetch('/api/telegram_data', {
                credentials: 'same-origin',
            });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();
            if (data.error) return;

            // تحديث الإحصائيات
            setText('stat-total-notifications', data.total_notifications);
            setText('stat-new-subscribers', data.new_subscribers);
            setText('stat-expired-subscribers', data.expired_subscribers);
            setText('stat-bulk-adds', data.bulk_adds);

            // تحديث قائمة السجل
            const container = document.getElementById('telegram-logs-container');
            if (!container || !Array.isArray(data.logs)) return;

            if (data.logs.length === 0) {
                container.innerHTML = '<div class="text-center text-muted py-3">لا توجد رسائل بعد</div>';
                return;
            }

            container.innerHTML = data.logs.map(function (log) {
                const statusClass = log.status === 'success' ? 'bg-success' : 'bg-danger';
                const typeLabel = TYPE_LABELS[log.type] || escapeHtml(log.type);

                return [
                    '<div class="list-group-item">',
                    '  <div class="d-flex justify-content-between align-items-center mb-1">',
                    '    <span class="badge ' + statusClass + ' bg-opacity-75">' + typeLabel + '</span>',
                    '    <small class="text-muted">' + escapeHtml(log.time) + '</small>',
                    '  </div>',
                    '  <div class="small text-truncate">' + escapeHtml(log.message) + '</div>',
                    '</div>',
                ].join('');
            }).join('');
        } catch (err) {
            console.warn('⚠️ فشل جلب بيانات التلجرام:', err.message);
        }
    }

    function setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    // ==========================================
    // تحديث يدوي
    // ==========================================
    function initRefreshButton() {
        const btn = document.getElementById('refreshLogsBtn');
        if (!btn) return;

        btn.addEventListener('click', async function () {
            this.disabled = true;
            lastFetch = 0; // تخطي الحد الأدنى
            await fetchTelegramData();
            setTimeout(() => { this.disabled = false; }, 500);
        });
    }

    // ==========================================
    // Polling ذكي: يتوقف عند إخفاء الصفحة
    // ==========================================
    let pollingTimer = null;

    function startPolling() {
        if (pollingTimer) return;
        pollingTimer = setInterval(fetchTelegramData, 30000); // 30 ثانية
    }

    function stopPolling() {
        if (pollingTimer) {
            clearInterval(pollingTimer);
            pollingTimer = null;
        }
    }

    document.addEventListener('visibilitychange', function () {
        if (document.hidden) {
            stopPolling();
        } else {
            fetchTelegramData();
            startPolling();
        }
    });

    // ==========================================
    // Init
    // ==========================================
    document.addEventListener('DOMContentLoaded', function () {
        initTokenToggle();
        initTestButton();
        initRefreshButton();

        // جلب أولي + بدء Polling
        fetchTelegramData();
        startPolling();
    });

})();
