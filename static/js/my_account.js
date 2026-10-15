// my_account.js

(function () {
    'use strict';

    // ==========================================
    // الحالة
    // ==========================================
    const POLL_INTERVAL = 5000;  // 5 ثواني (بدل 1.5s)
    const FETCH_TIMEOUT = 8000;

    let pollTimer = null;
    let isPageVisible = !document.hidden;

    const section = document.getElementById('liveSpeedSection');
    const LIVE_ENDPOINT = section ? section.dataset.endpoint : '';
    const refreshBtn = document.getElementById('refreshBtn');
    const REFRESH_ENDPOINT = refreshBtn ? refreshBtn.dataset.endpoint : '';

    // ==========================================
    // Helpers
    // ==========================================
    function formatBytes(bytes) {
        bytes = Number(bytes) || 0;
        if (bytes === 0) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        return (bytes / Math.pow(1024, i)).toFixed(2) + ' ' + units[i];
    }

    function setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    async function fetchJson(url, options = {}) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT);

        try {
            const res = await fetch(url, {
                ...options,
                credentials: 'same-origin',
                signal: controller.signal,
            });
            clearTimeout(timer);
            if (!res.ok) throw new Error('HTTP ' + res.status);
            return await res.json();
        } catch (err) {
            clearTimeout(timer);
            throw err;
        }
    }

    // ==========================================
    // السرعة الحية
    // ==========================================
    async function updateLiveSpeed() {
        if (!LIVE_ENDPOINT || !isPageVisible) return;

        try {
            const data = await fetchJson(LIVE_ENDPOINT, { method: 'POST' });
            if (!data.ok) return;

            const statusEl = document.getElementById('liveStatus');

            if (data.online) {
                setText('liveDownload', data.download_speed);
                setText('liveDownloadUnit', data.download_unit);
                setText('liveUpload', data.upload_speed);
                setText('liveUploadUnit', data.upload_unit);

                setText('totalDownload', formatBytes(data.download_total));
                setText('totalUpload', formatBytes(data.upload_total));

                const total = Number(data.download_total) + Number(data.upload_total);
                if (total > 0) {
                    const downPct = (Number(data.download_total) / total * 100).toFixed(1);
                    const upPct = (Number(data.upload_total) / total * 100).toFixed(1);
                    const barDown = document.getElementById('barDown');
                    const barUp = document.getElementById('barUp');
                    if (barDown) barDown.style.width = downPct + '%';
                    if (barUp) barUp.style.width = upPct + '%';
                }

                if (statusEl) {
                    statusEl.innerHTML = '<span class="live-dot-anim"></span> مباشر';
                    statusEl.style.background = 'rgba(239, 68, 68, 0.15)';
                    statusEl.style.color = '#ef4444';
                    statusEl.style.borderColor = 'rgba(239, 68, 68, 0.4)';
                }
            } else {
                setText('liveDownload', '0.0');
                setText('liveDownloadUnit', 'kbps');
                setText('liveUpload', '0.0');
                setText('liveUploadUnit', 'kbps');

                if (statusEl) {
                    statusEl.innerHTML = '<i class="bi bi-wifi-off"></i> غير متصل';
                    statusEl.style.background = 'rgba(100,116,139,0.15)';
                    statusEl.style.color = '#94a3b8';
                    statusEl.style.borderColor = 'rgba(148,163,184,0.4)';
                }
            }
        } catch (err) {
            console.warn('Live speed error:', err.message);
        }
    }

    // ==========================================
    // تحديث البيانات الكاملة
    // ==========================================
    async function refreshData() {
        if (!refreshBtn || !REFRESH_ENDPOINT) return;

        const originalHTML = refreshBtn.innerHTML;
        refreshBtn.disabled = true;
        refreshBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> جاري التحديث...';

        try {
            const data = await fetchJson(REFRESH_ENDPOINT, { method: 'POST' });

            if (data.ok) {
                setText('ipValue', data.ip || '—');
                setText('connectedAt', data.connected_at || '—');
                setText('uptimeValue', data.uptime || '—');
                setText('totalDownload', formatBytes(data.tx_bytes));
                setText('totalUpload', formatBytes(data.rx_bytes));

                const total = Number(data.rx_bytes) + Number(data.tx_bytes);
                if (total > 0) {
                    const downPct = (Number(data.tx_bytes) / total * 100).toFixed(1);
                    const upPct = (Number(data.rx_bytes) / total * 100).toFixed(1);
                    document.getElementById('barDown').style.width = downPct + '%';
                    document.getElementById('barUp').style.width = upPct + '%';
                }

                const now = new Date().toLocaleTimeString('ar-EG', {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                });
                setText('lastUpdate', 'آخر تحديث: ' + now);

                refreshBtn.innerHTML = '<i class="bi bi-check-circle-fill"></i> تم التحديث';
                setTimeout(() => {
                    refreshBtn.disabled = false;
                    refreshBtn.innerHTML = originalHTML;
                }, 1500);
            } else {
                refreshBtn.disabled = false;
                refreshBtn.innerHTML = originalHTML;
            }
        } catch (err) {
            console.error('Refresh error:', err.message);
            refreshBtn.disabled = false;
            refreshBtn.innerHTML = originalHTML;
        }
    }

    // ==========================================
    // Polling ذكي
    // ==========================================
    function startPolling() {
        if (pollTimer) return;
        pollTimer = setInterval(updateLiveSpeed, POLL_INTERVAL);
    }

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    document.addEventListener('visibilitychange', function () {
        isPageVisible = !document.hidden;
        if (isPageVisible) {
            updateLiveSpeed();  // تحديث فوري
            startPolling();
        } else {
            stopPolling();
        }
    });

    // ==========================================
    // Init
    // ==========================================
    document.addEventListener('DOMContentLoaded', function () {
        if (refreshBtn) {
            refreshBtn.addEventListener('click', refreshData);
        }

        // تحديث أولي + بدء
        updateLiveSpeed();
        startPolling();
    });

})();
