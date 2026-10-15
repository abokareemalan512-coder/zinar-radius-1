// import_backup.js

(function () {
    'use strict';

    const MAX_SIZE_MB = 20;
    const MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024;
    const ALLOWED_EXT = ['.rsc', '.txt'];

    document.addEventListener('DOMContentLoaded', function () {

        const form = document.getElementById('uploadForm');
        const dropzone = document.getElementById('dropzone');
        const fileInput = document.getElementById('fileInput');
        const filePreview = document.getElementById('filePreview');
        const fileName = document.getElementById('fileName');
        const fileSize = document.getElementById('fileSize');
        const removeBtn = document.getElementById('removeFileBtn');
        const submitBtn = document.getElementById('submitBtn');
        const submitText = document.getElementById('submitText');
        const progressBar = document.getElementById('progressBar');
        const progressBarInner = document.getElementById('progressBarInner');

        if (!form || !dropzone || !fileInput) return;

        // ==========================================
        // Helpers
        // ==========================================
        function formatSize(bytes) {
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
            return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
        }

        function isAllowedFile(name) {
            const lower = name.toLowerCase();
            return ALLOWED_EXT.some(ext => lower.endsWith(ext));
        }

        function showError(msg) {
            alert('❌ ' + msg);
        }

        // ==========================================
        // اختيار الملف
        // ==========================================
        function handleFile(file) {
            if (!file) return;

            // تحقق من الامتداد
            if (!isAllowedFile(file.name)) {
                showError('صيغة الملف غير مدعومة.\n\n' +
                          'الصيغ المدعومة: ' + ALLOWED_EXT.join(', '));
                return;
            }

            // تحقق من الحجم
            if (file.size > MAX_SIZE_BYTES) {
                showError('حجم الملف كبير جدًا (' + formatSize(file.size) + ').\n' +
                          'الحد الأقصى: ' + MAX_SIZE_MB + ' MB');
                return;
            }

            // تحقق من عدم كونه فارغًا
            if (file.size === 0) {
                showError('الملف فارغ.');
                return;
            }

            // معاينة
            fileName.textContent = file.name;
            fileSize.textContent = '(' + formatSize(file.size) + ')';
            filePreview.classList.remove('d-none');
            dropzone.style.display = 'none';

            // تفعيل زر الإرسال
            submitBtn.disabled = false;
        }

        // ==========================================
        // Drag & Drop
        // ==========================================
        ['dragenter', 'dragover'].forEach(event => {
            dropzone.addEventListener(event, function (e) {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.add('dragover');
            });
        });

        ['dragleave', 'drop'].forEach(event => {
            dropzone.addEventListener(event, function (e) {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.remove('dragover');
            });
        });

        dropzone.addEventListener('drop', function (e) {
            const files = e.dataTransfer.files;
            if (files && files.length > 0) {
                fileInput.files = files;
                handleFile(files[0]);
            }
        });

        // ==========================================
        // Click على الـ dropzone يفتح نافذة الاختيار
        // ==========================================
        dropzone.addEventListener('click', function () {
            fileInput.click();
        });

        // ==========================================
        // تغيير الملف
        // ==========================================
        fileInput.addEventListener('change', function (e) {
            const file = e.target.files[0];
            handleFile(file);
        });

        // ==========================================
        // إزالة الملف
        // ==========================================
        removeBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            fileInput.value = '';
            filePreview.classList.add('d-none');
            dropzone.style.display = '';
            submitBtn.disabled = true;
        });

        // ==========================================
        // إرسال مع Progress Bar
        // ==========================================
        form.addEventListener('submit', function (e) {
            if (!fileInput.files || fileInput.files.length === 0) {
                e.preventDefault();
                showError('الرجاء اختيار ملف أولًا');
                return false;
            }

            e.preventDefault();

            // تحقق نهائي
            const file = fileInput.files[0];
            if (!isAllowedFile(file.name) || file.size > MAX_SIZE_BYTES) {
                showError('الملف غير صالح');
                return false;
            }

            // إظهار شريط التقدم
            progressBar.classList.remove('d-none');
            progressBarInner.style.width = '0%';

            // تغيير حالة الزر
            submitBtn.disabled = true;
            submitText.textContent = 'جاري الاستيراد...';
            submitBtn.querySelector('i').className = 'spinner-border spinner-border-sm';

            // رفع باستخدام XHR (لدعم progress)
            const xhr = new XMLHttpRequest();
            const formData = new FormData(form);

            xhr.upload.addEventListener('progress', function (evt) {
                if (evt.lengthComputable) {
                    const pct = (evt.loaded / evt.total) * 100;
                    progressBarInner.style.width = pct + '%';
                    submitText.textContent = 'جاري الرفع... ' + Math.round(pct) + '%';
                }
            });

            xhr.addEventListener('load', function () {
                if (xhr.status === 200) {
                    progressBarInner.style.width = '100%';
                    submitText.textContent = 'جاري المعالجة...';
                    // نجاح — إعادة تحميل الصفحة
                    // Flask سيردّ بـ redirect أو HTML
                    document.open();
                    document.write(xhr.responseText);
                    document.close();
                } else {
                    alert('❌ فشل الاستيراد (رمز ' + xhr.status + ')');
                    resetButton();
                }
            });

            xhr.addEventListener('error', function () {
                alert('❌ خطأ في الاتصال بالخادم');
                resetButton();
            });

            xhr.addEventListener('timeout', function () {
                alert('❌ انتهت المهلة — الملف كبير أو الاتصال بطيء');
                resetButton();
            });

            function resetButton() {
                submitBtn.disabled = false;
                submitText.textContent = 'بدء الاستيراد إلى الموقع';
                submitBtn.querySelector('i').className = 'bi bi-upload';
                progressBar.classList.add('d-none');
            }

            xhr.timeout = 120000; // دقيقتان
            xhr.open('POST', form.action || window.location.href);
            xhr.send(formData);
        });

    });
})();
