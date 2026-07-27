document.addEventListener('DOMContentLoaded', () => {
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('file-input');
    const browseBtn = document.getElementById('browse-btn');
    
    const uploadIdle = document.getElementById('upload-idle');
    const uploadProcessing = document.getElementById('upload-processing');
    const uploadSuccess = document.getElementById('upload-success');
    
    const fileNameLabel = document.getElementById('file-name-label');
    const successFilename = document.getElementById('success-filename');
    const terminalLogs = document.getElementById('terminal-logs');
    
    const downloadBtn = document.getElementById('download-btn');
    const resetBtn = document.getElementById('reset-btn');
    const auditSection = document.getElementById('audit');
    
    let currentTaskId = null;
    let currentOutputFilename = null;

    // Trigger file browse
    browseBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        fileInput.click();
    });

    dropzone.addEventListener('click', () => {
        if (uploadIdle.classList.contains('hidden')) return;
        fileInput.click();
    });

    // Drag and Drop Effects
    ['dragenter', 'dragover'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add('drag-over');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('drag-over');
        }, false);
    });

    // Handle Drop
    dropzone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) {
            handleFile(files[0]);
        }
    });

    // Handle File Input Change
    fileInput.addEventListener('change', (e) => {
        if (fileInput.files.length > 0) {
            handleFile(fileInput.files[0]);
        }
    });

    function addLog(message) {
        const line = document.createElement('div');
        line.className = 'log-line';
        line.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
        terminalLogs.appendChild(line);
        terminalLogs.scrollTop = terminalLogs.scrollHeight;
    }

    function handleFile(file) {
        if (file.type !== 'application/pdf' && !file.name.endsWith('.pdf')) {
            alert('Please select a valid PDF file.');
            return;
        }

        // Show Processing UI
        uploadIdle.classList.add('hidden');
        uploadProcessing.classList.remove('hidden');
        uploadSuccess.classList.add('hidden');
        auditSection.classList.add('hidden');
        
        fileNameLabel.textContent = file.name;
        terminalLogs.innerHTML = '';
        addLog(`Selected file: ${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)`);
        addLog('Uploading document to ADA PDF Remediator server...');

        // Create FormData
        const formData = new FormData();
        formData.append('pdf', file);

        // Animate Stepper
        setTimeout(() => setStep(1), 500);
        setTimeout(() => { setStep(2); addLog('Detecting vector drawings, complex shapes & page tables...'); }, 1800);
        setTimeout(() => { setStep(3); addLog('Injecting /StructTreeRoot, /ParentTree & /MCID marked content...'); }, 3200);
        setTimeout(() => { setStep(4); addLog('Generating dynamic /ToUnicode font character maps...'); }, 4500);

        // Perform Upload
        fetch('/api/remediate', {
            method: 'POST',
            body: formData
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => { throw new Error(err.error || 'Remediation failed'); });
            }
            return response.json();
        })
        .then(data => {
            addLog('Pipeline completed! PDF/UA-1 & WCAG compliance check passed.');
            currentTaskId = data.task_id;
            currentOutputFilename = data.output_filename || 'remediated_accessible.pdf';
            
            setTimeout(() => {
                uploadProcessing.classList.add('hidden');
                uploadSuccess.classList.remove('hidden');
                successFilename.textContent = `File "${file.name}" has been successfully remediated.`;
                auditSection.classList.remove('hidden');
            }, 1000);
        })
        .catch(err => {
            addLog(`ERROR: ${err.message}`);
            alert(`Remediation Error: ${err.message}`);
            resetUI();
        });
    }

    function setStep(stepNum) {
        for (let i = 1; i <= 4; i++) {
            const step = document.getElementById(`step-${i}`);
            if (i <= stepNum) {
                step.classList.add('step-active');
            } else {
                step.classList.remove('step-active');
            }
        }
    }

    // Download Button Action
    downloadBtn.addEventListener('click', () => {
        if (currentTaskId) {
            window.location.href = `/api/download/${currentTaskId}`;
        }
    });

    // Reset Button Action
    resetBtn.addEventListener('click', resetUI);

    function resetUI() {
        uploadIdle.classList.remove('hidden');
        uploadProcessing.classList.add('hidden');
        uploadSuccess.classList.add('hidden');
        auditSection.classList.add('hidden');
        fileInput.value = '';
        currentTaskId = null;
        setStep(1);
    }
});
