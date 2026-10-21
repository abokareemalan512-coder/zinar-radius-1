// subscribers.js

// ==========================================
// مزامنة من MikroTik
// ==========================================
function initSyncButton() {
    const syncBtn = document.getElementById('syncBtn');
    if (!syncBtn) return;

    syncBtn.addEventListener('click', function () {
        const originalHTML = this.innerHTML;
        this.disabled = true;
        this.innerHTML = '<span class="spinner-border spinner-border-sm"></span> جاري المزامنة...';

        fetch('/subscribers/sync-now', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.ok) {
                    let msg = `✅ تم المزامنة بنجاح!\n\n` +
                              `📊 عدد الراوترات: ${data.routers}\n` +
                              `🔍 تم فحص: ${data.checked} مشترك\n` +
                              `🟢 متصل الآن: ${data.online}\n` +
                              `🔄 تم تحديث: ${data.updated}`;
                    if (data.errors && data.errors.length > 0) {
                        msg += `\n\n⚠️ أخطاء:\n${data.errors.slice(0, 3).join('\n')}`;
                    }
                    alert(msg);
                    location.reload();
                } else {
                    alert('❌ فشل المزامنة: ' + (data.error || 'خطأ غير معروف'));
                }
            })
            .catch(err => alert('❌ خطأ في الاتصال: ' + err.message))
            .finally(() => {
                syncBtn.disabled = false;
                syncBtn.innerHTML = originalHTML;
            });
    });
}

// ==========================================
// عرض/إخفاء كلمة المرور (بجلب آمن)
// ==========================================
function initPasswordToggle() {
    const cache = {};

    document.querySelectorAll('.js-toggle-password').forEach(btn => {
        btn.addEventListener('click', async function () {
            const id = this.dataset.id;
            const username = this.dataset.username;
            const span = document.querySelector(`.password-field[data-id="${id}"]`);
            const eye = document.getElementById(`eye-${id}`);
            if (!span || !eye) return;

            // إخفاء
            if (span.textContent !== '••••••') {
                span.textContent = '••••••';
                eye.className = 'bi bi-eye text-muted';
                return;
            }

            // عرض — جلب من السيرفر
            try {
                if (!cache[id]) {
                    const res = await fetch(`/api/subscriber/password/${id}`);
                    const data = await res.json();
                    if (!data.ok) throw new Error(data.error || 'فشل الجلب');
                    cache[id] = data.password;
                }
                span.textContent = cache[id];
                eye.className = 'bi bi-eye-slash text-primary';

                // إخفاء تلقائي بعد 10 ثواني
                setTimeout(() => {
                    span.textContent = '••••••';
                    eye.className = 'bi bi-eye text-muted';
                }, 10000);
            } catch (err) {
                alert('❌ تعذر جلب كلمة المرور: ' + err.message);
            }
        });
    });
}

// ==========================================
// فتح نموذج التعديل
// ==========================================
function initEditModal() {
    document.querySelectorAll('.js-edit-sub').forEach(btn => {
        btn.addEventListener('click', function () {
            const id = this.dataset.subId;
            const name = this.dataset.subName;
            const username = this.dataset.subUsername;
            const pkg = this.dataset.subPackage;

            const form = document.getElementById('editSubForm');
            form.action = '/subscribers/update/' + id;
            document.getElementById('sub_name').value = name;
            document.getElementById('sub_username').value = username;
            document.getElementById('sub_password').value = '';
            document.getElementById('sub_days').value = '';
            document.getElementById('sub_package').value = pkg || '';

            new bootstrap.Modal(document.getElementById('editSubModal')).show();
        });
    });
}

// ==========================================
// التحديد الجماعي
// ==========================================
function initBulkSelection() {
    const selectAll = document.getElementById('selectAll');
    if (!selectAll) return;

    selectAll.addEventListener('change', function () {
        document.querySelectorAll('.sub-checkbox').forEach(cb => {
            cb.checked = this.checked;
        });
        updateBulkBar();
    });

    document.querySelectorAll('.sub-checkbox').forEach(cb => {
        cb.addEventListener('change', updateBulkBar);
    });
}

function updateBulkBar() {
    const checked = document.querySelectorAll('.sub-checkbox:checked');
    const bar = document.getElementById('bulkBar');
    const cnt = document.getElementById('selectedCount');
    if (!bar || !cnt) return;

    if (checked.length > 0) {
        bar.style.display = 'block';
        cnt.textContent = checked.length;
    } else {
        bar.style.display = 'none';
    }
}

function clearSelection() {
    document.querySelectorAll('.sub-checkbox').forEach(cb => { cb.checked = false; });
    const sa = document.getElementById('selectAll');
    if (sa) sa.checked = false;
    updateBulkBar();
}

function getSelectedIds() {
    const ids = [];
    document.querySelectorAll('.sub-checkbox:checked').forEach(cb => { ids.push(cb.value); });
    return ids;
}

function exportSelected(format) {
    const ids = getSelectedIds();
    if (ids.length === 0) {
        alert('⚠️ الرجاء تحديد مشترك واحد على الأقل');
        return;
    }
    window.location.href = `/subscribers/export/${format}?ids=` + ids.join(',');
}

function deleteSelected() {
    const ids = getSelectedIds();
    if (ids.length === 0) return;
    if (!confirm(`⚠️ سيتم حذف ${ids.length} مشترك من قاعدة البيانات فقط.\nهل أنت متأكد؟`)) return;
    document.getElementById('bulkDeleteIds').value = ids.join(',');
    document.getElementById('bulkDeleteForm').submit();
}

// ==========================================
// تأكيدات الحذف
// ==========================================
function initConfirmations() {
    document.querySelectorAll('.js-confirm-link').forEach(link => {
        link.addEventListener('click', function (e) {
            const msg = this.dataset.confirmMsg || 'هل أنت متأكد؟';
            if (!confirm(msg)) e.preventDefault();
        });
    });

    document.querySelectorAll('.js-confirm-form').forEach(form => {
        form.addEventListener('submit', function (e) {
            const msg = this.dataset.confirmMsg || 'هل أنت متأكد؟';
            if (!confirm(msg)) e.preventDefault();
        });
    });
}

// ==========================================
// Initialization
// ==========================================
document.addEventListener('DOMContentLoaded', function () {
    initSyncButton();
    initPasswordToggle();
    initEditModal();
    initBulkSelection();
    initConfirmations();
});
