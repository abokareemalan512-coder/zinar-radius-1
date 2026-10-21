// login_subscriber.js

(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {

        // ============ عرض/إخفاء كلمة المرور ============
        const toggleBtn = document.getElementById('togglePasswordBtn');
        const toggleIcon = document.getElementById('togglePasswordIcon');
        const passwordInput = document.getElementById('input_password');

        if (toggleBtn && toggleIcon && passwordInput) {
            toggleBtn.addEventListener('click', function () {
                if (passwordInput.type === 'password') {
                    passwordInput.type = 'text';
                    toggleIcon.className = 'bi bi-eye-slash';
                    toggleBtn.setAttribute('aria-label', 'إخفاء كلمة المرور');
                } else {
                    passwordInput.type = 'password';
                    toggleIcon.className = 'bi bi-eye';
                    toggleBtn.setAttribute('aria-label', 'عرض كلمة المرور');
                }
            });
        }

        // ============ تحقق قبل الإرسال + Loading ============
        const form = document.getElementById('loginForm');
        const submitBtn = document.getElementById('submitBtn');

        if (form && submitBtn) {
            form.addEventListener('submit', function (e) {
                const username = document.getElementById('input_username').value.trim();
                const password = passwordInput.value;

                if (!username || !password) {
                    e.preventDefault();
                    return false;
                }

                // تحويل الزر إلى حالة "جاري"
                const originalHTML = submitBtn.innerHTML;
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> جاري التحقق...';

                // إعادة الزر بعد 8 ثواني احتياطًا (في حال فشل الطلب)
                setTimeout(() => {
                    if (submitBtn.disabled) {
                        submitBtn.disabled = false;
                        submitBtn.innerHTML = originalHTML;
                    }
                }, 8000);
            });
        }

    });
})();
