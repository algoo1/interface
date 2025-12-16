const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const uploadContent = document.getElementById('upload-content');
const loadingState = document.getElementById('loading-state');
const resultState = document.getElementById('result-state');
const fileName = document.getElementById('file-name');
const videoOutput = document.getElementById('output-video');
const downloadBtn = document.getElementById('download-btn');
const resetBtn = document.getElementById('reset-btn');
const errorState = document.getElementById('error-state');
const errorText = document.getElementById('error-text');
const retryBtn = document.getElementById('retry-btn');


// Drag and Drop Events
['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, preventDefaults, false);
});

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, highlight, false);
});

['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, unhighlight, false);
});

function highlight(e) {
    dropZone.classList.add('drag-over');
}

function unhighlight(e) {
    dropZone.classList.remove('drag-over');
}

dropZone.addEventListener('drop', handleDrop, false);

function handleDrop(e) {
    const dt = e.dataTransfer;
    const files = dt.files;
    handleFiles(files);
}

fileInput.addEventListener('change', function () {
    handleFiles(this.files);
});

// Main Actions
function handleFiles(files) {
    if (files.length > 0) {
        const file = files[0];
        if (file.type.startsWith('video/')) {
            uploadFile(file);
        } else {
            showError('يرجى تحميل ملف فيديو صالح.');
        }
    }
}

const logsContainer = document.getElementById('logs-container');
const logsContent = document.getElementById('logs-content');

function addLog(message) {
    logsContainer.style.display = 'block';
    const time = new Date().toLocaleTimeString();
    const entry = document.createElement('div');
    entry.style.borderBottom = "1px solid rgba(255,255,255,0.05)";
    entry.style.padding = "2px 0";
    entry.textContent = `[${time}] ${message}`;
    logsContent.appendChild(entry);
    logsContainer.scrollTop = logsContainer.scrollHeight;
    console.log(`[Log] ${message}`);
}

async function uploadFile(file) {
    // UI Update
    uploadContent.classList.add('hidden');
    loadingState.classList.remove('hidden');
    errorState.classList.add('hidden');

    addLog(`Starting upload for file: ${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)`);

    // Prepare Data
    const formData = new FormData();
    formData.append('file', file);

    try {
        // Updated for Vercel: Use relative path. 
        // Note: This requires accessing the site via the same port/domain (e.g. uvicorn -> localhost:8000)
        const apiUrl = '/api/upscale';
        addLog(`Sending POST request to ${apiUrl}...`);

        const response = await fetch(apiUrl, {
            method: 'POST',
            body: formData
        });

        addLog(`Response received. Status: ${response.status} ${response.statusText}`);

        const contentType = response.headers.get("content-type");
        if (contentType && contentType.indexOf("application/json") !== -1) {
            var data = await response.json();
            if (!response.ok) {
                addLog(`Server returned error: ${data.detail}`);
                throw new Error(data.detail || 'فشل التحميل');
            }
        } else {
            const textHTML = await response.text();
            console.error("Non-JSON Response:", textHTML);
            const snippet = textHTML.substring(0, 200).replace(/</g, "&lt;");
            addLog(`Non-JSON Error received: ${snippet}`);
            throw new Error(`خطأ في السيرفر (${response.status}): ${snippet}...`);
        }

        addLog("Processing response data...");
        if (data.url) {
            addLog(`Success! Video URL: ${data.url}`);
            showResult(data.url);
        } else if (data.output) {
            // Fallback for raw output message
            console.log("Raw output:", data.output);
            addLog("Warning: Raw output format received.");
            // It might be that output IS a url string, let's allow it
            if (typeof data.output === 'string' && data.output.startsWith('http')) {
                showResult(data.output);
            } else {
                showResultUrlOrRaw(data.output);
            }
        } else {
            addLog("Error: Invalid response structure.");
            throw new Error('استجابة غير صالحة من السيرفر');
        }

    } catch (error) {
        console.error('Error:', error);
        addLog(`EXCEPTION: ${error.message}`);
        showError(error.message);
    }
}

function showResultUrlOrRaw(output) {
    if (typeof output === 'object') {
        showError("مخرجات معقدة: " + JSON.stringify(output));
    } else {
        showError("المخرجات: " + output);
    }
}

function showResult(url) {
    loadingState.classList.add('hidden');
    resultState.classList.remove('hidden');
    videoOutput.src = url;
    downloadBtn.href = url;
}

function showError(msg) {
    loadingState.classList.add('hidden');
    uploadContent.classList.add('hidden');
    resultState.classList.add('hidden');
    errorState.classList.remove('hidden');
    errorText.innerHTML = msg; // Changed to innerHTML to support <br> or simple text
}


function resetUI() {
    resultState.classList.add('hidden');
    errorState.classList.add('hidden');
    uploadContent.classList.remove('hidden');
    fileInput.value = ''; // Reset input
    videoOutput.src = '';
    logsContent.innerHTML = ''; // Clear logs on reset
    logsContainer.style.display = 'none';
}

resetBtn.addEventListener('click', resetUI);
retryBtn.addEventListener('click', resetUI);
