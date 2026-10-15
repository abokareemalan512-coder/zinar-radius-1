// login_admin.js

(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {

        // ============ عرض/إخفاء كلمة المرور ============
        const toggleBtn = document.getElementById('togglePasswordBtn');
        const toggleIcon = document.getElementById('togglePasswordIcon');
        const passwordInput = document.getElementById('input_password');

        if (toggleBtn && toggleIcon && passwordInput) {
            toggleBtn.addEventListener('click', function () {
                const isPassword = passwordInput.type === 'password';
                passwordInput.type = isPassword ? 'text' : 'password';
                toggleIcon.className = isPassword ? 'bi bi-eye-slash' : 'bi bi-eye';
                toggleBtn.setAttribute('aria-label',
                    isPassword ? 'إخفاء كلمة المرور' : 'عرض كلمة المرور');
            });
        }

        // ============ Loading state ============
        const form = document.getElementById('adminLoginForm');
        const submitBtn = document.getElementById('submitBtn');

        if (form && submitBtn) {
            form.addEventListener('submit', function (e) {
                const username = document.getElementById('input_username').value.trim();
                const password = passwordInput.value;

                if (!username || !password) {
                    e.preventDefault();
                    return false;
                }

                const originalHTML = submitBtn.innerHTML;
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> جاري التحقق...';

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
