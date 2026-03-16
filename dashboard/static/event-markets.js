const eventQueryForm = document.getElementById('eventQueryForm');
const eventPlatformInput = document.getElementById('eventPlatform');
const eventIdentifierInput = document.getElementById('eventIdentifier');
const eventQueryButton = document.getElementById('eventQueryButton');
const queryHint = document.getElementById('queryHint');
const eventLookupStatus = document.getElementById('eventLookupStatus');
const eventResultTitle = document.getElementById('eventResultTitle');
const eventResultMeta = document.getElementById('eventResultMeta');
const eventMarketsBody = document.getElementById('eventMarketsBody');
const dashboardAuth = window.dashboardAuth || {
  fetchWithAuth: fetch,
  isAuthRequired: () => false,
};

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function setStatus(message, kind = 'info') {
  if (!message) {
    eventLookupStatus.className = 'status-banner';
    eventLookupStatus.textContent = '';
    return;
  }

  eventLookupStatus.className = `status-banner ${kind}`;
  eventLookupStatus.textContent = message;
}

function renderEmptyRow(message) {
  eventMarketsBody.innerHTML = `
    <tr>
      <td colspan="2" class="empty-state">${escapeHtml(message)}</td>
    </tr>
  `;
}

function updateHint() {
  queryHint.textContent = eventPlatformInput.value === 'kalshi'
    ? 'Kalshi 使用 event ticker，请注意字母全部大写，例如 KXOSCARACTO-26。'
    : 'Polymarket 使用 event slug，例如 oscars-2026-best-actor-winner。';
}

function renderMarkets(markets) {
  if (!Array.isArray(markets) || markets.length === 0) {
    renderEmptyRow('该事件下未返回任何 market。');
    return;
  }

  eventMarketsBody.innerHTML = markets.map((market) => `
    <tr>
      <td>${escapeHtml(market.identifier || '-')}</td>
      <td>${escapeHtml(market.title || '-')}</td>
    </tr>
  `).join('');
}

eventPlatformInput.addEventListener('change', updateHint);

eventQueryForm.addEventListener('submit', async (event) => {
  event.preventDefault();

  const platform = eventPlatformInput.value;
  const identifier = eventIdentifierInput.value.trim();
  if (!identifier) {
    setStatus('请先填写事件标识符。', 'error');
    renderEmptyRow('请输入事件标识符后再查询。');
    return;
  }

  eventQueryButton.disabled = true;
  setStatus('正在查询事件及其 market 列表...', 'info');
  renderEmptyRow('查询中...');

  try {
    const params = new URLSearchParams({platform, identifier});
    const response = await dashboardAuth.fetchWithAuth(`/api/event-markets?${params.toString()}`);
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.error || '查询失败');
    }

    eventResultTitle.textContent = payload.event_title || identifier;
    eventResultMeta.textContent = `${platform} / ${payload.event_identifier} / 共 ${payload.markets.length} 个 market`;
    renderMarkets(payload.markets);
    setStatus('查询完成。', 'success');
  } catch (error) {
    eventResultTitle.textContent = '查询失败';
    eventResultMeta.textContent = '请检查平台与事件标识符是否正确。';
    renderEmptyRow('未能获取 market 列表。');
    if (!dashboardAuth.isAuthRequired(error)) {
      setStatus(error.message || '查询失败', 'error');
    }
  } finally {
    eventQueryButton.disabled = false;
  }
});

updateHint();