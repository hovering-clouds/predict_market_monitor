const monitorsDiv = document.getElementById('monitors');
const form = document.getElementById('createForm');
const arbitrageForm = document.getElementById('arbitrageForm');

async function listMonitors() {
  const res = await fetch('/api/monitors');
  const data = await res.json();
  monitorsDiv.innerHTML = '';
  data.forEach(m => addMonitorCard(m));
}

function addMonitorCard(m) {
  const card = document.createElement('div');
  card.className = m.arbitrage_pair ? 'card arbitrage-card' : 'card';
  card.id = `mon-${m.id}`;
  
  let contentHtml = `
    <div><strong>${m.type}</strong> — ${m.market} (<span class="freq">${m.freq}s</span>)</div>
    <div>状态: <span class="status">${m.status}</span></div>
  `;
  
  // 套利对展示
  if (m.arbitrage_pair) {
    contentHtml += `
      <div style="margin-top:8px;padding-top:8px;border-top:1px solid #ddd">
        <div><strong>市场1:</strong> ${m.market1} (${m.type1})</div>
        <div><strong>市场2:</strong> ${m.market2} (${m.type2})</div>
        <div><strong>最小价差:</strong> ${m.min_spread}</div>
      </div>
      <div class="ob" style="margin-top:8px">
        <div><em>等待数据...</em></div>
      </div>
      <div class="arb-spread" style="display:none" id="arb-result-${m.id}"></div>
    `;
  } else {
    contentHtml += `<div class="ob"><em>等待数据...</em></div>`;
  }
  
  contentHtml += `
    <div class="actions">
      <button class="cancel">取消</button>
    </div>
  `;
  
  card.innerHTML = contentHtml;

  const cancelBtn = card.querySelector('.cancel');
  cancelBtn.onclick = async () => {
    await fetch(`/api/monitors/${m.id}`, {method: 'DELETE'});
    removeMonitorCard(m.id);
  };

  monitorsDiv.appendChild(card);
  subscribeToMonitor(m.id, card, m.arbitrage_pair || false);
}

function removeMonitorCard(id) {
  const el = document.getElementById(`mon-${id}`);
  if (el) el.remove();
}

function subscribeToMonitor(id, card, isArbitrage) {
  const evt = new EventSource(`/stream/${id}`);
  const obDiv = card.querySelector('.ob');
  const statusSpan = card.querySelector('.status');
  const arbResultDiv = card.querySelector(`#arb-result-${id}`);

  evt.onmessage = (e) => {
    try {
      const d = JSON.parse(e.data);
      statusSpan.textContent = '运行中';
      
      if (isArbitrage) {
        // 套利对数据显示
        obDiv.innerHTML = `
          <div><strong>市场1 Bid:</strong> ${d.market1_bid ? d.market1_bid.value : '-'} @ ${d.market1_bid ? d.market1_bid.quantity : '-'}</div>
          <div><strong>市场1 Ask:</strong> ${d.market1_ask ? d.market1_ask.value : '-'} @ ${d.market1_ask ? d.market1_ask.quantity : '-'}</div>
          <div style="margin-top:6px"><strong>市场2 Bid:</strong> ${d.market2_bid ? d.market2_bid.value : '-'} @ ${d.market2_bid ? d.market2_bid.quantity : '-'}</div>
          <div><strong>市场2 Ask:</strong> ${d.market2_ask ? d.market2_ask.value : '-'} @ ${d.market2_ask ? d.market2_ask.quantity : '-'}</div>
        `;
        
        if (d.arbitrage_spread !== undefined) {
          const spreadDisplay = d.arbitrage_spread > 0 ? 
            `<span style="color:#28a745">可套利价差: ${d.arbitrage_spread.toFixed(6)}</span>` :
            `<span style="color:#dc3545">无套利机会 (价差: ${d.arbitrage_spread.toFixed(6)})</span>`;
          arbResultDiv.innerHTML = `
            ${spreadDisplay} | <span>可套利数量: ${d.arbitrage_quantity ? d.arbitrage_quantity.toFixed(6) : '0'}</span>
          `;
          arbResultDiv.style.display = 'block';
        }
      } else {
        // 单个监控数据显示
        obDiv.innerHTML = `
          <div>Bid: ${d.bid ? d.bid.value : '-'} @ ${d.bid ? d.bid.quantity : '-'} </div>
          <div>Ask: ${d.ask ? d.ask.value : '-'} @ ${d.ask ? d.ask.quantity : '-'} </div>
        `;
      }
    } catch (err) {
      obDiv.textContent = '解析数据出错: ' + err.message;
    }
  };

  evt.onerror = () => {
    statusSpan.textContent = '连接中断';
    evt.close();
  };
}

form.onsubmit = async (ev) => {
  ev.preventDefault();
  const type = document.getElementById('monitorType').value;
  const market = document.getElementById('market').value;
  const freq = Number(document.getElementById('freq').value) || 5;

  const res = await fetch('/api/monitors', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({type, market, freq})
  });

  if (res.ok) {
    const data = await res.json();
    addMonitorCard(data);
    form.reset();
  } else {
    alert('创建失败');
  }
}

arbitrageForm.onsubmit = async (ev) => {
  ev.preventDefault();
  const type1 = document.getElementById('arb-type-1').value;
  const market1 = document.getElementById('arb-market-1').value;
  const freq1 = Number(document.getElementById('arb-freq-1').value) || 5;
  
  const type2 = document.getElementById('arb-type-2').value;
  const market2 = document.getElementById('arb-market-2').value;
  const freq2 = Number(document.getElementById('arb-freq-2').value) || 5;
  
  const min_spread = Number(document.getElementById('arb-min-spread').value) || 0.01;

  const res = await fetch('/api/arbitrage', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      type1, market1, freq1,
      type2, market2, freq2,
      min_spread
    })
  });

  if (res.ok) {
    const data = await res.json();
    addMonitorCard(data);
    arbitrageForm.reset();
  } else {
    const error = await res.json();
    alert('创建套利监控失败: ' + error.error);
  }
}

// 初始加载现有监控
listMonitors();
