// routers.js

document.addEventListener('DOMContentLoaded', function () {

    // ============ فتح نموذج التعديل ============
    document.querySelectorAll('.js-edit-router').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const d = this.dataset;
            const form = document.getElementById('editRouterForm');

            form.action = '/routers/update/' + d.routerId;
            document.getElementById('edit_name').value = d.routerName || '';
            document.getElementById('edit_ip').value = d.routerIp || '';
            document.getElementById('edit_username').value = d.routerUsername || '';
            document.getElementById('edit_password').value = '';
            document.getElementById('edit_port').value = d.routerPort || '22';
            document.getElementById('edit_api_port').value = d.routerApiPort || '8728';

            new bootstrap.Modal(document.getElementById('editRouterModal')).show();
        });
    });

    // ============ تأكيد الحذف ============
    document.querySelectorAll('.js-delete-router').forEach(function (link) {
        link.addEventListener('click', function (e) {
            const name = this.dataset.routerName || 'هذا الراوتر';
            if (!confirm('هل أنت متأكد من حذف الراوتر "' + name + '"؟')) {
                e.preventDefault();
                return false;
            }
        });
    });

    // ============ تأكيد التعيين كرئيسي ============
    document.querySelectorAll('.js-set-master').forEach(function (link) {
        link.addEventListener('click', function (e) {
            const name = this.dataset.routerName || 'هذا الراوتر';
            if (!confirm('تعيين "' + name + '" كراوتر رئيسي؟')) {
                e.preventDefault();
                return false;
            }
        });
    });
});
