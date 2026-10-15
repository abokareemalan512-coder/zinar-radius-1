// traffic_monitor.js

(function () {
    'use strict';

    // ============ الإعدادات ============
    const MAX_DATA_POINTS = 30;
    const UPDATE_INTERVAL = 3000;
    const FETCH_TIMEOUT = 8000;
    const STORAGE_KEY = 'traffic_monitor_state';
    const DIRECTION_KEY = 'traffic_direction_reversed';

    // ============ الحالة ============
    let uploadChart = null;
    let downloadChart = null;
    let monitoringInterval = null;
    let isDirectionReversed = false;
    let allInterfaces = [];
    let selectedInterface = '';
    let isPageVisible = !document.hidden;

    const uploadData = [];
    const downloadData = [];
    const labels = [];

    // ============ DOM ============
    const routerSelect = document.getElementById('routerSelect');
    const interfaceSearch = document.getElementById('interfaceSearch');
    const interfaceDropdown = document.getElementById('interfaceDropdown');
    const interfaceSelect = document.getElementById('interfaceSelect');
    const clearSearchBtn = document.getElementById('clearSearchBtn');
    const directionBtn = document.getElementById('directionBtn');
    const directionText = document.getElementById('directionText');
    const directionInfo = document.getElementById('directionInfo');
    const directionInfoText = document.getElementById('directionInfoText');
    const startBtn = document.getElementById('startBtn');
    const stopBtn = document.getElementById('stopBtn');
    const monitoringArea = document.getElementById('monitoringArea');
    const connectionStatus = document.getElementById('connectionStatus');
    const statusText = document.getElementById('statusText');

    // ============ Helpers ============
    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str).replace(/[&<>"']/g, m => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[m]));
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

    function setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    function parseSpeedToMbps(speedStr) {
        if (!speedStr) return 0;
        const s = String(speedStr);
        if (s.includes('Gbps')) return parseFloat(s) * 1000;
        if (s.includes('Mbps')) return parseFloat(s);
        if (s.includes('kbps')) return parseFloat(s) / 1000;
        const num = parseFloat(s);
        return isNaN(num) ? 0 : num / 1000000;
    }

    // ============ الاتجاه ============
    function loadDirection() {
        try {
            isDirectionReversed = localStorage.getItem(DIRECTION_KEY) === 'true';
        } catch (e) {
            isDirectionReversed = false;
        }
        updateDirectionUI();
    }

    function saveDirection() {
        try {
            localStorage.setItem(DIRECTION_KEY, String(isDirectionReversed));
        } catch (e) {}
    }

    function updateDirectionUI() {
        if (!directionBtn || !directionText) return;
        if (isDirectionReversed) {
            directionBtn.classList.add('reversed');
            directionText.textContent = 'الاتجاه: معكوس (LAN)';
            if (directionInfoText) {
                directionInfoText.innerHTML = 'الاتجاه الحالي: <strong style="color:#f59e0b;">معكوس</strong> — مناسب لمنافذ LAN';
            }
        } else {
            directionBtn.classList.remove('reversed');
            directionText.textContent = 'الاتجاه: تلقائي (WAN)';
            if (directionInfoText) {
                directionInfoText.innerHTML = 'الاتجاه الحالي: <strong>تلقائي</strong> — مناسب لمنافذ WAN';
            }
        }
    }

    function toggleDirection() {
        isDirectionReversed = !isDirectionReversed;
        saveDirection();
        updateDirectionUI();

        uploadData.length = 0;
        downloadData.length = 0;
        labels.length = 0;

        if (uploadChart && downloadChart) {
            uploadChart.data.labels = labels;
            uploadChart.data.datasets[0].data = uploadData;
            uploadChart.update();
            downloadChart.data.labels = labels;
            downloadChart.data.datasets[0].data = downloadData;
            downloadChart.update();
        }

        const routerId = routerSelect ? routerSelect.value : '';
        if (routerId && selectedInterface && monitoringInterval) {
            fetchTrafficData(routerId, selectedInterface);
        }
    }

    // ============ حالة التخزين ============
    function saveState(routerId, interfaceName, isMonitoring) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({
                routerId, interfaceName, isMonitoring,
            }));
        } catch (e) {}
    }

    function loadState() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (e) { return null; }
    }

    function clearState() {
        try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
    }

    // ============ Charts ============
    function initCharts() {
        const ctxUpload = document.getElementById('uploadChart').getContext('2d');
        const ctxDownload = document.getElementById('downloadChart').getContext('2d');

        const commonOptions = {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 200 },
            plugins: { legend: { display: false } },
            scales: {
                x: { display: false },
                y: {
                    beginAtZero: true,
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#94a3b8', font: { size: 10 } },
                },
            },
            elements: {
                point: { radius: 0, hitRadius: 10 },
                line: { tension: 0.4, borderWidth: 2.5 },
            },
        };

        uploadChart = new Chart(ctxUpload, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    data: uploadData,
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.15)',
                    fill: true,
                }],
            },
            options: commonOptions,
        });

        downloadChart = new Chart(ctxDownload, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    data: downloadData,
                    borderColor: '#22c55e',
                    backgroundColor: 'rgba(34, 197, 94, 0.15)',
                    fill: true,
                }],
            },
            options: commonOptions,
        });
    }

    // ============ المنافذ ============
    function renderInterfaceDropdown(interfaces) {
        if (!interfaceDropdown) return;

        if (interfaces.length === 0) {
            interfaceDropdown.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">لا توجد نتائج</div>';
            return;
        }

        interfaceDropdown.innerHTML = interfaces.map(iface => {
            const statusClass = iface.running ? 'iface-running' : 'iface-idle';
            const statusText = iface.running ? '🟢 يعمل' : '⚪ متوقف';
            const isSelected = iface.name === selectedInterface ? 'selected' : '';
            const safeName = escapeHtml(iface.name);
            const safeType = escapeHtml(iface.type || 'unknown');

            return `
                <div class="interface-item ${isSelected}" data-iface-name="${safeName}">
                    <div class="iface-info">
                        <div class="iface-name">${safeName}</div>
                        <div class="iface-meta">${safeType}</div>
                    </div>
                    <span class="iface-status ${statusClass}">${statusText}</span>
                </div>
            `;
        }).join('');
    }

    async function fetchInterfaces(routerId, callback) {
        if (!interfaceSearch || !connectionStatus) return;

        interfaceSearch.value = '';
        interfaceSearch.placeholder = '⏳ جاري الجلب...';
        interfaceSearch.disabled = true;
        connectionStatus.style.display = 'block';
        statusText.textContent = 'جاري الاتصال بالـ API...';

        try {
            const data = await fetchJson(`/api/traffic/interfaces/${routerId}`);

            if (data.ok) {
                allInterfaces = data.interfaces || [];
                interfaceSearch.disabled = false;
                interfaceSearch.placeholder = `🔍 ابحث عن منفذ... (${allInterfaces.length})`;
                statusText.textContent = `✅ تم جلب ${allInterfaces.length} منفذ عبر API`;
                renderInterfaceDropdown(allInterfaces);
                if (callback) callback();
            } else {
                interfaceSearch.placeholder = '❌ خطأ في الجلب';
                statusText.textContent = '❌ ' + (data.error || 'فشل الاتصال');
                interfaceSearch.disabled = false;
            }
        } catch (err) {
            console.error('Fetch interfaces error:', err);
            interfaceSearch.placeholder = '❌ فشل الاتصال';
            statusText.textContent = '❌ ' + err.message;
            interfaceSearch.disabled = false;
        }
    }

    function filterInterfaces() {
        if (!interfaceSearch) return;
        const query = interfaceSearch.value.toLowerCase().trim();
        clearSearchBtn.style.display = query ? 'block' : 'none';

        const filtered = query
            ? allInterfaces.filter(iface =>
                iface.name.toLowerCase().includes(query) ||
                (iface.type && iface.type.toLowerCase().includes(query)))
            : allInterfaces;

        renderInterfaceDropdown(filtered);
        interfaceDropdown.classList.add('show');
    }

    function showInterfaceDropdown() {
        if (allInterfaces.length > 0) interfaceDropdown.classList.add('show');
    }

    function clearInterfaceSearch() {
        interfaceSearch.value = '';
        clearSearchBtn.style.display = 'none';
        renderInterfaceDropdown(allInterfaces);
        interfaceDropdown.classList.add('show');
    }

    function selectInterface(name) {
        selectedInterface = name;
        interfaceSelect.value = name;
        interfaceSearch.value = name;
        clearSearchBtn.style.display = 'block';
        interfaceDropdown.classList.remove('show');

        const routerId = routerSelect.value;
        saveState(routerId, name, false);
    }

    function onRouterChange() {
        const routerId = routerSelect.value;

        if (!routerId) {
            interfaceSearch.value = '';
            interfaceSearch.disabled = true;
            interfaceSearch.placeholder = '🔍 ابحث عن منفذ...';
            interfaceDropdown.classList.remove('show');
            connectionStatus.style.display = 'none';
            directionInfo.style.display = 'none';
            allInterfaces = [];
            selectedInterface = '';
            clearState();
            return;
        }

        selectedInterface = '';
        interfaceSelect.value = '';
        interfaceDropdown.innerHTML = '';
        directionInfo.style.display = 'block';
        saveState(routerId, '', false);
        fetchInterfaces(routerId, null);
    }

    // ============ المراقبة ============
    async function fetchTrafficData(routerId, interfaceName) {
        if (!isPageVisible) return;

        try {
            const data = await fetchJson(`/api/traffic/stats/${routerId}/${encodeURIComponent(interfaceName)}`);
            if (!data.ok) {
                console.warn('Traffic error:', data.error);
                return;
            }

            const stats = data.stats;
            const rxRateVal = parseSpeedToMbps(stats.rx_rate);
            const txRateVal = parseSpeedToMbps(stats.tx_rate);
            const rxByteVal = parseInt(stats.rx_byte) || 0;
            const txByteVal = parseInt(stats.tx_byte) || 0;

            let uploadRateVal, downloadRateVal, uploadByteVal, downloadByteVal;
            if (isDirectionReversed) {
                uploadRateVal = rxRateVal;
                downloadRateVal = txRateVal;
                uploadByteVal = rxByteVal;
                downloadByteVal = txByteVal;
            } else {
                uploadRateVal = txRateVal;
                downloadRateVal = rxRateVal;
                uploadByteVal = txByteVal;
                downloadByteVal = rxByteVal;
            }

            const uploadGB = (uploadByteVal / (1024 * 1024 * 1024)).toFixed(2);
            const downloadGB = (downloadByteVal / (1024 * 1024 * 1024)).toFixed(2);

            setText('uploadRate', uploadRateVal.toFixed(2));
            setText('downloadRate', downloadRateVal.toFixed(2));
            setText('uploadTotal', uploadGB + ' GB');
            setText('downloadTotal', downloadGB + ' GB');
            setText('uploadRateBadge', uploadRateVal.toFixed(2) + ' Mbps');
            setText('downloadRateBadge', downloadRateVal.toFixed(2) + ' Mbps');

            document.getElementById('uploadProgress').style.width = Math.min((uploadRateVal / 100) * 100, 100) + '%';
            document.getElementById('downloadProgress').style.width = Math.min((downloadRateVal / 100) * 100, 100) + '%';

            const now = new Date().toLocaleTimeString('ar-EG', {
                hour: '2-digit', minute: '2-digit', second: '2-digit',
            });
            labels.push(now);
            uploadData.push(uploadRateVal);
            downloadData.push(downloadRateVal);

            if (labels.length > MAX_DATA_POINTS) {
                labels.shift();
                uploadData.shift();
                downloadData.shift();
            }

            uploadChart.update('none');
            downloadChart.update('none');
        } catch (err) {
            console.warn('Traffic fetch error:', err.message);
        }
    }

    function startMonitoring() {
        const routerId = routerSelect.value;
        const interfaceName = selectedInterface;

        if (!routerId || !interfaceName) {
            alert('⚠️ الرجاء اختيار الراوتر والمنفذ أولاً');
            return;
        }

        monitoringArea.style.display = 'flex';
        connectionStatus.style.display = 'block';
        directionInfo.style.display = 'block';
        startBtn.style.display = 'none';
        stopBtn.style.display = 'inline-block';
        statusText.textContent = `📡 مراقبة المنفذ: ${interfaceName}`;

        uploadData.length = 0;
        downloadData.length = 0;
        labels.length = 0;

        if (!uploadChart) initCharts();

        saveState(routerId, interfaceName, true);

        fetchTrafficData(routerId, interfaceName);
        monitoringInterval = setInterval(() => fetchTrafficData(routerId, interfaceName), UPDATE_INTERVAL);
    }

    function stopMonitoring() {
        clearInterval(monitoringInterval);
        monitoringInterval = null;
        startBtn.style.display = 'inline-block';
        stopBtn.style.display = 'none';
        connectionStatus.style.display = 'none';
        saveState(routerSelect.value, selectedInterface, false);
    }

    // ============ Init ============
    document.addEventListener('DOMContentLoaded', function () {
        loadDirection();

        // ============ ربط الأحداث ============
        if (routerSelect) {
            routerSelect.disabled = false;
            routerSelect.addEventListener('change', onRouterChange);
        }

        if (interfaceSearch) {
            interfaceSearch.addEventListener('input', filterInterfaces);
            interfaceSearch.addEventListener('focus', showInterfaceDropdown);
        }

        if (clearSearchBtn) clearSearchBtn.addEventListener('click', clearInterfaceSearch);
        if (directionBtn) directionBtn.addEventListener('click', toggleDirection);
        if (startBtn) startBtn.addEventListener('click', startMonitoring);
        if (stopBtn) stopBtn.addEventListener('click', stopMonitoring);

        // اختيار منفذ من القائمة
        if (interfaceDropdown) {
            interfaceDropdown.addEventListener('click', function (e) {
                const item = e.target.closest('.interface-item');
                if (item && item.dataset.ifaceName) {
                    selectInterface(item.dataset.ifaceName);
                }
            });
        }

        // إغلاق القائمة عند النقر خارجها
        document.addEventListener('click', function (e) {
            const wrapper = document.querySelector('.interface-search-wrapper');
            if (wrapper && !wrapper.contains(e.target)) {
                if (interfaceDropdown) interfaceDropdown.classList.remove('show');
            }
        });

        // إيقاف/استئناف Polling حسب رؤية الصفحة
        document.addEventListener('visibilitychange', function () {
            isPageVisible = !document.hidden;
            if (!isPageVisible && monitoringInterval) {
                clearInterval(monitoringInterval);
                monitoringInterval = null;
            } else if (isPageVisible && monitoringInterval === null && startBtn.style.display === 'none') {
                const routerId = routerSelect.value;
                if (routerId && selectedInterface) {
                    fetchTrafficData(routerId, selectedInterface);
                    monitoringInterval = setInterval(() => fetchTrafficData(routerId, selectedInterface), UPDATE_INTERVAL);
                }
            }
        });

        // ============ استرجاع الحالة ============
        const state = loadState();
        if (!state || !state.routerId) return;

        routerSelect.value = state.routerId;
        if (routerSelect.value !== state.routerId) return;

        fetchInterfaces(state.routerId, function () {
            if (state.interfaceName) {
                selectInterface(state.interfaceName);
                if (state.isMonitoring) {
                    setTimeout(startMonitoring, 500);
                }
            }
        });
    });

})();
