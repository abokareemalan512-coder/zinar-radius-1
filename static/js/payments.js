// payments.js

(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {

        // ==========================================
        // تأكيد دفعة
        // ==========================================
        document.querySelectorAll('.js-complete-payment').forEach(btn => {
            btn.addEventListener('click', async function () {
                const id = this.dataset.paymentId;
                if (!id) return;

                if (!confirm('هل تريد تأكيد هذه الدفعة؟')) return;

                const originalHTML = this.innerHTML;
                this.disabled = true;
                this.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

                try {
                    const res = await fetch(`/payments/${id}/complete`, {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: { 'X-Requested-With': 'XMLHttpRequest' },
                    });

                    const data = await res.json();

                    if (data.ok) {
                        // نجاح — حرك الصف وأعد التحميل
                        const row = document.querySelector(`tr[data-payment-id="${id}"]`);
                        if (row) {
                            row.style.transition = 'opacity 0.4s';
                            row.style.opacity = '0';
                        }
                        setTimeout(() => location.reload(), 400);
                    } else {
                        alert('❌ ' + (data.error || 'فشل التأكيد'));
                        this.disabled = false;
                        this.innerHTML = originalHTML;
                    }
                } catch (err) {
                    alert('❌ خطأ في الاتصال: ' + err.message);
                    this.disabled = false;
                    this.innerHTML = originalHTML;
                }
            });
        });

    });
})();
