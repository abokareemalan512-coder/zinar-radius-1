// bulk_add.js

document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('bulkForm');
    const pkgSelect = document.getElementById('input_package');
    const pkgHint = document.getElementById('pkgHint');
    const userTypeRadios = document.querySelectorAll('input[name="user_type"]');

    // ============ معاينة الأسماء ============
    function randomString(len, mode) {
        const letters = 'abcdefghijkmnpqrstuvwxyz';
        const numbers = '23456789';
        let chars = '';
        if (mode === 'letters') chars = letters;
        else if (mode === 'mixed') chars = letters + numbers;
        else chars = numbers;

        let out = '';
        for (let i = 0; i < len; i++) {
            out += chars.charAt(Math.floor(Math.random() * chars.length));
        }
        return out;
    }

    function updatePreview() {
        const mode = document.querySelector('input[name="char_mode"]:checked').value;
        const prefix = document.getElementById('input_prefix').value || '';
        const len = Math.min(Math.max(parseInt(document.getElementById('input_length').value) || 6, 4), 20);
        const samples = [];
        for (let i = 0; i < 5; i++) {
            samples.push(prefix + randomString(len, mode));
        }
        document.getElementById('previewText').textContent = samples.join('  |  ');
    }

    // ============ ملخص الطلب ============
    function updateSummary() {
        const count = document.getElementById('input_count').value || '0';
        const pkg = pkgSelect.value || '—';
        const pwMode = document.querySelector('input[name="password_mode"]:checked').value;

        let pwText = 'عشوائي';
        if (pwMode === 'same_as_username') pwText = 'نفس الاسم';
        if (pwMode === 'fixed') pwText = 'ثابت';

        document.getElementById('sum_count').textContent = count;
        document.getElementById('sum_pkg').textContent = pkg;
        document.getElementById('sum_pw').textContent = pwText;
    }

    // ============ فلترة الباقات حسب النوع ============
    function filterPackages() {
        const selectedType = document.querySelector('input[name="user_type"]:checked').value;
        const options = pkgSelect.querySelectorAll('option[data-type]');
        let visibleCount = 0;

        options.forEach(opt => {
            if (opt.dataset.type === selectedType) {
                opt.style.display = '';
                visibleCount++;
            } else {
                opt.style.display = 'none';
                if (opt.selected) pkgSelect.value = '';
            }
        });

        pkgHint.textContent = `تم عرض ${visibleCount} باقة متوافقة`;
        updateSummary();
    }

    // ============ إظهار/إخفاء حقول كلمة المرور ============
    function updatePasswordFields() {
        const mode = document.querySelector('input[name="password_mode"]:checked').value;
        document.getElementById('random_pass_div').style.display = (mode === 'random') ? 'block' : 'none';
        document.getElementById('fixed_password_div').style.display = (mode === 'fixed') ? 'block' : 'none';
        updateSummary();
    }

    // ============ ربط الأحداث ============
    document.querySelectorAll('input[name="char_mode"], input[name="prefix"], input[name="random_length"], input[name="count"], input[name="password_length"]')
        .forEach(el => el.addEventListener('input', () => { updatePreview(); updateSummary(); }));

    userTypeRadios.forEach(r => r.addEventListener('change', filterPackages));

    document.querySelectorAll('input[name="password_mode"]').forEach(r =>
        r.addEventListener('change', updatePasswordFields));

    pkgSelect.addEventListener('change', updateSummary);
    document.getElementById('input_count').addEventListener('input', updateSummary);

    // ============ التحقق قبل الإرسال ============
    form.addEventListener('submit', function (e) {
        const prefix = document.getElementById('input_prefix').value.trim();
        if (prefix && !/^[A-Za-z0-9_\-]+$/.test(prefix)) {
            e.preventDefault();
            alert('❌ البادئة تحتوي على رموز غير مسموحة');
            return false;
        }

        const pwMode = document.querySelector('input[name="password_mode"]:checked').value;
        if (pwMode === 'fixed') {
            const fixed = document.getElementById('input_fixed_pw').value.trim();
            if (!fixed || fixed.length < 3) {
                e.preventDefault();
                alert('❌ كلمة المرور الثابتة قصيرة جداً');
                return false;
            }
        }

        const pkg = pkgSelect.value;
        if (!pkg) {
            e.preventDefault();
            alert('❌ الرجاء اختيار باقة');
            return false;
        }

        const selectedType = document.querySelector('input[name="user_type"]:checked').value;
        const selectedOpt = pkgSelect.querySelector(`option[value="${pkg}"]`);
        if (selectedOpt && selectedOpt.dataset.type !== selectedType) {
            e.preventDefault();
            alert('❌ الباقة لا تتوافق مع نوع المستخدم المختار');
            return false;
        }

        // تأكيد
        const count = document.getElementById('input_count').value;
        if (!confirm(`سيتم إنشاء ${count} مشترك وإضافتهم إلى RADIUS. متابعة؟`)) {
            e.preventDefault();
            return false;
        }

        return true;
    });

    // التشغيل الأولي
    updatePreview();
    filterPackages();
    updatePasswordFields();
    updateSummary();
});
