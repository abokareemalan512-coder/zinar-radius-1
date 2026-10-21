// packages.js

document.addEventListener('DOMContentLoaded', function () {

    // ============ فتح نموذج التعديل ============
    document.querySelectorAll('.js-edit-pkg').forEach(btn => {
        btn.addEventListener('click', function () {
            const d = this.dataset;
            const form = document.getElementById('editPackageForm');

            // تعيين الـ action URL بأمان
            form.action = '/packages/update/' + d.pkgId;

            // ملء الحقول بأمان (بلا XSS)
            document.getElementById('pkg_name').value = d.pkgName || '';
            document.getElementById('pkg_speed').value = d.pkgSpeed || '';
            document.getElementById('pkg_price').value = d.pkgPrice || '0';
            document.getElementById('pkg_duration').value = d.pkgDuration || '1';
            document.getElementById('pkg_unit').value = d.pkgUnit || 'days';
            document.getElementById('pkg_user_type').value = d.pkgType || 'pppoe';

            // إظهار المودال
            new bootstrap.Modal(document.getElementById('editPackageModal')).show();
        });
    });

    // ============ تأكيد الحذف ============
    document.querySelectorAll('.js-delete-pkg').forEach(link => {
        link.addEventListener('click', function (e) {
            const name = this.dataset.pkgName || 'هذه الباقة';
            if (!confirm(`هل أنت متأكد من حذف الباقة "${name}"؟\n\n⚠️ سيتم إزالة السرعة من كل المشتركين المرتبطين بها.`)) {
                e.preventDefault();
                return false;
            }
        });
    });

    // ============ تحقق من صيغة السرعة ============
    const speedInputs = document.querySelectorAll('input[name="speed"]');
    const speedPattern = /^\d+[KMG]?(\/\d+[KMG]?)?$/i;

    speedInputs.forEach(input => {
        input.addEventListener('blur', function () {
            const val = this.value.trim();
            if (val && !speedPattern.test(val)) {
                this.classList.add('is-invalid');
            } else {
                this.classList.remove('is-invalid');
            }
        });
    });

    // ============ تحقق نموذج الإضافة ============
    const addForm = document.getElementById('addPkgForm');
    if (addForm) {
        addForm.addEventListener('submit', function (e) {
            const speed = this.querySelector('input[name="speed"]').value.trim();
            if (speed && !speedPattern.test(speed)) {
                e.preventDefault();
                alert('❌ صيغة السرعة غير صحيحة\n\nالاستخدام الصحيح:\n• 5M\n• 5M/5M\n• 10M/2M');
                return false;
            }
        });
    }

    // ============ تحقق نموذج التعديل ============
    const editForm = document.getElementById('editPackageForm');
    if (editForm) {
        editForm.addEventListener('submit', function (e) {
            const speed = document.getElementById('pkg_speed').value.trim();
            if (speed && !speedPattern.test(speed)) {
                e.preventDefault();
                alert('❌ صيغة السرعة غير صحيحة');
                return false;
            }
        });
    }
});
