const logSettingsForm = document.getElementById('logSettingsForm');
const logLineCountInput = document.getElementById('logLineCount');
const logRefreshSecondsInput = document.getElementById('logRefreshSeconds');
const logToggleButton = document.getElementById('logToggleButton');
const logManualRefreshButton = document.getElementById('logManualRefreshButton');
const logStatusBanner = document.getElementById('logStatusBanner');
const logViewer = document.getElementById('logViewer');
const logViewerTitle = document.getElementById('logViewerTitle');
const logViewerMeta = document.getElementById('logViewerMeta');

let logLineCount = 50;
let refreshSeconds = 2;
let autoRefreshEnabled = true;
let refreshTimer = null;
let lastRenderedSignature = '';

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function setLogStatus(message, kind = 'info') {
  logStatusBanner.className = `status-banner ${kind}`;
  logStatusBanner.textContent = message;
}

function classifyLine(line) {
  if (/\b(error|critical|traceback|exception|fatal)\b/i.test(line)) {
    return 'error';
  }
  if (/\b(warn|warning)\b/i.test(line)) {
    return 'warn';
  }
  return 'normal';
}

function renderLogLines(lines) {
  if (!Array.isArray(lines) || lines.length === 0) {
    logViewer.innerHTML = '<div class="log-empty">日志文件为空，或尚未产生输出。</div>';
    return;
  }

  logViewer.innerHTML = lines.map((line, index) => {
    const lineClass = classifyLine(line);
    return `
      <div class="log-line ${lineClass}">
        <span class="log-line-number">${index + 1}</span>
        <span class="log-line-text">${escapeHtml(line)}</span>
      </div>
    `;
  }).join('');

  logViewer.scrollTop = logViewer.scrollHeight;
}

async function fetchLatestLogs(showLoadingStatus = false) {
  if (showLoadingStatus) {
    setLogStatus('正在获取日志内容...', 'info');
  }

  try {
    const params = new URLSearchParams({lines: String(logLineCount)});
    const response = await fetch(`/api/logs/latest?${params.toString()}`);
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.error || '拉取日志失败');
    }

    const signature = Array.isArray(payload.lines) ? payload.lines.join('\n') : '';
    if (signature !== lastRenderedSignature) {
      renderLogLines(payload.lines || []);
      lastRenderedSignature = signature;
    }

    logViewerTitle.textContent = payload.log_file || '日志文件';
    logViewerMeta.textContent = `显示最新 ${payload.line_count} 行 / 请求 ${payload.requested_lines} 行 / 更新时间 ${new Date().toLocaleTimeString()}`;
    setLogStatus(autoRefreshEnabled ? '自动刷新中' : '已暂停自动刷新', 'success');
  } catch (error) {
    setLogStatus(error.message || '日志加载失败', 'error');
  }
}

function restartAutoRefreshTimer() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }

  if (!autoRefreshEnabled) {
    return;
  }

  refreshTimer = setInterval(() => {
    fetchLatestLogs(false);
  }, refreshSeconds * 1000);
}

function toggleAutoRefresh() {
  autoRefreshEnabled = !autoRefreshEnabled;
  logToggleButton.textContent = autoRefreshEnabled ? '暂停自动刷新' : '恢复自动刷新';
  setLogStatus(autoRefreshEnabled ? '自动刷新中' : '已暂停自动刷新', autoRefreshEnabled ? 'success' : 'info');
  restartAutoRefreshTimer();
}

logSettingsForm.addEventListener('submit', (event) => {
  event.preventDefault();

  const nextLines = Number(logLineCountInput.value);
  const nextRefreshSeconds = Number(logRefreshSecondsInput.value);

  logLineCount = Number.isFinite(nextLines) ? Math.min(200, Math.max(1, Math.floor(nextLines))) : 50;
  refreshSeconds = Number.isFinite(nextRefreshSeconds) ? Math.min(30, Math.max(1, Math.floor(nextRefreshSeconds))) : 2;

  logLineCountInput.value = String(logLineCount);
  logRefreshSecondsInput.value = String(refreshSeconds);

  restartAutoRefreshTimer();
  fetchLatestLogs(true);
});

logToggleButton.addEventListener('click', toggleAutoRefresh);
logManualRefreshButton.addEventListener('click', () => fetchLatestLogs(true));

restartAutoRefreshTimer();
fetchLatestLogs(true);