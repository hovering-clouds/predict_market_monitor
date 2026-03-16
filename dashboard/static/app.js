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
  const initialStatus = typeof m.status === 'string' ? m.status : 'running';
  const initialArbCount = Number.isFinite(Number(m.arb_cnt)) ? Number(m.arb_cnt) : 0;
  const initialMarket1Budget = asNumber(m.market1_budget);
  const initialMarket2Budget = asNumber(m.market2_budget);
  const initialMarket1Remaining = asNumber(m.market1_remaining_budget);
  const initialMarket2Remaining = asNumber(m.market2_remaining_budget);
  const initialMarket1Consumed = asNumber(m.market1_consumed_budget);
  const initialMarket2Consumed = asNumber(m.market2_consumed_budget);
  const market1BudgetText = initialMarket1Budget === null ? '无限制' : initialMarket1Budget.toFixed(6);
  const market2BudgetText = initialMarket2Budget === null ? '无限制' : initialMarket2Budget.toFixed(6);
  const market1RemainingText = initialMarket1Remaining === null ? market1BudgetText : initialMarket1Remaining.toFixed(6);
  const market2RemainingText = initialMarket2Remaining === null ? market2BudgetText : initialMarket2Remaining.toFixed(6);
  const market1ConsumedText = initialMarket1Consumed === null ? '0.000000' : initialMarket1Consumed.toFixed(6);
  const market2ConsumedText = initialMarket2Consumed === null ? '0.000000' : initialMarket2Consumed.toFixed(6);
  
  let contentHtml;
  
  // 套利对展示
  if (m.arbitrage_pair) {
    contentHtml = `
      <div><strong>${m.type1}</strong> - <strong>${m.type2}</strong> (<span class="freq">${m.freq}s</span>)</div>
      <div>状态: <span class="status">${initialStatus}</span></div>
    `;
    contentHtml += `
      <div style="margin-top:8px;padding-top:8px;border-top:1px solid #ddd">
        <div><strong>市场1:</strong> ${m.market1} (${m.type1})</div>
        <div><strong>市场2:</strong> ${m.market2} (${m.type2})</div>
        <div><strong>最小价差:</strong> ${m.min_spread}</div>
        <div><strong>最大套利比例:</strong> ${(m.max_arb_ratio * 100).toFixed(1)}%</div>
        <div><strong>最大套利数量:</strong> ${isFinite(m.max_arb_quantity) ? m.max_arb_quantity : '无限制'}</div>
        <div><strong>市场1预算:</strong> <span class="market1-budget">${market1BudgetText}</span></div>
        <div><strong>市场2预算:</strong> <span class="market2-budget">${market2BudgetText}</span></div>
        <div><strong>市场1剩余预算:</strong> <span class="market1-remaining-budget">${market1RemainingText}</span></div>
        <div><strong>市场2剩余预算:</strong> <span class="market2-remaining-budget">${market2RemainingText}</span></div>
        <div><strong>市场1已用预算:</strong> <span class="market1-consumed-budget">${market1ConsumedText}</span></div>
        <div><strong>市场2已用预算:</strong> <span class="market2-consumed-budget">${market2ConsumedText}</span></div>
        <div><strong>已套利次数:</strong> <span class="arb-cnt">${initialArbCount}</span></div>
      </div>
      <div class="ob" style="margin-top:8px">
        <div><em>等待数据...</em></div>
      </div>
      <div class="arb-spread" style="display:none" id="arb-result-${m.id}"></div>
    `;
  } else {
    contentHtml = `
      <div><strong>${m.type}</strong> — ${m.market} (<span class="freq">${m.freq}s</span>)</div>
      <div>状态: <span class="status">${initialStatus}</span></div>
    `;
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

function asNumber(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function formatFixed(v, digits = 6, fallback = '-') {
  const n = asNumber(v);
  return n === null ? fallback : n.toFixed(digits);
}

function subscribeToMonitor(id, card, isArbitrage) {
  const evt = new EventSource(`/stream/${id}`);
  const obDiv = card.querySelector('.ob');
  const statusSpan = card.querySelector('.status');
  const arbCountSpan = card.querySelector('.arb-cnt');
  const market1BudgetSpan = card.querySelector('.market1-budget');
  const market2BudgetSpan = card.querySelector('.market2-budget');
  const market1RemainingSpan = card.querySelector('.market1-remaining-budget');
  const market2RemainingSpan = card.querySelector('.market2-remaining-budget');
  const market1ConsumedSpan = card.querySelector('.market1-consumed-budget');
  const market2ConsumedSpan = card.querySelector('.market2-consumed-budget');
  const arbResultDiv = card.querySelector(`#arb-result-${id}`);

  evt.onmessage = (e) => {
    try {
      const d = JSON.parse(e.data);
      const status = typeof d.status === 'string' ? d.status : 'running';
      statusSpan.textContent = status;
      
      if (isArbitrage) {
        const arbCount = asNumber(d.arb_cnt);
        const market1Budget = asNumber(d.market1_budget);
        const market2Budget = asNumber(d.market2_budget);
        const market1Remaining = asNumber(d.market1_remaining_budget);
        const market2Remaining = asNumber(d.market2_remaining_budget);
        const market1Consumed = asNumber(d.market1_consumed_budget);
        const market2Consumed = asNumber(d.market2_consumed_budget);
        if (arbCountSpan && arbCount !== null) {
          arbCountSpan.textContent = String(Math.max(0, Math.floor(arbCount)));
        }
        if (market1BudgetSpan) {
          market1BudgetSpan.textContent = market1Budget === null ? '无限制' : market1Budget.toFixed(6);
        }
        if (market2BudgetSpan) {
          market2BudgetSpan.textContent = market2Budget === null ? '无限制' : market2Budget.toFixed(6);
        }
        if (market1RemainingSpan) {
          market1RemainingSpan.textContent = market1Remaining === null ? '-' : market1Remaining.toFixed(6);
        }
        if (market2RemainingSpan) {
          market2RemainingSpan.textContent = market2Remaining === null ? '-' : market2Remaining.toFixed(6);
        }
        if (market1ConsumedSpan) {
          market1ConsumedSpan.textContent = market1Consumed === null ? '-' : market1Consumed.toFixed(6);
        }
        if (market2ConsumedSpan) {
          market2ConsumedSpan.textContent = market2Consumed === null ? '-' : market2Consumed.toFixed(6);
        }

        const market1Ask = d.market1_ask && typeof d.market1_ask === 'object' ? d.market1_ask : null;
        const market1Bid = d.market1_bid && typeof d.market1_bid === 'object' ? d.market1_bid : null;
        const market2Ask = d.market2_ask && typeof d.market2_ask === 'object' ? d.market2_ask : null;
        const market2Bid = d.market2_bid && typeof d.market2_bid === 'object' ? d.market2_bid : null;

        // 套利对数据显示
        obDiv.innerHTML = `
          <div><strong>市场1 Ask:</strong> ${market1Ask ? market1Ask.value : '-'} @ ${market1Ask ? market1Ask.quantity : '-'}</div>
          <div><strong>市场1 Bid:</strong> ${market1Bid ? market1Bid.value : '-'} @ ${market1Bid ? market1Bid.quantity : '-'}</div>
          <div style="margin-top:6px"><strong>市场2 Ask:</strong> ${market2Ask ? market2Ask.value : '-'} @ ${market2Ask ? market2Ask.quantity : '-'}</div>
          <div><strong>市场2 Bid:</strong> ${market2Bid ? market2Bid.value : '-'} @ ${market2Bid ? market2Bid.quantity : '-'}</div>
        `;
        
        if (d.arbitrage_spread !== undefined) {
          const spread = asNumber(d.arbitrage_spread);
          const spreadDisplay = spread === null ?
            `<span style="color:#6c757d">可套利价差: -</span>` :
            (spread > 0 ?
              `<span style="color:#28a745">可套利价差: ${spread.toFixed(6)}</span>` :
              `<span style="color:#dc3545">无套利机会 (价差: ${spread.toFixed(6)})</span>`);

          const quantityText = formatFixed(d.arbitrage_quantity, 6, '0.000000');
          const cumulativeProfitText = formatFixed(d.cumulative_profit, 6, '0.000000');
          const cumulativeExposureText = formatFixed(d.cumulative_risk_exposure, 6, '0.000000');
          const cumulativeFeeText = formatFixed(d.cumulative_fee, 6, '0.000000');
          const arbCountText = arbCount === null ? '-' : String(Math.max(0, Math.floor(arbCount)));
          const market1RemainingText = market1Remaining === null ? '-' : market1Remaining.toFixed(6);
          const market2RemainingText = market2Remaining === null ? '-' : market2Remaining.toFixed(6);
          const market1ConsumedText = market1Consumed === null ? '-' : market1Consumed.toFixed(6);
          const market2ConsumedText = market2Consumed === null ? '-' : market2Consumed.toFixed(6);

          arbResultDiv.innerHTML = `
            <div>${spreadDisplay} | <span>可套利数量: ${quantityText}</span></div>
            <div style="margin-top:6px">
              <span>累计获利: ${cumulativeProfitText}</span>
              <span> | 累计敞口: ${cumulativeExposureText}</span>
              <span> | 累计交易费: ${cumulativeFeeText}</span>
              <span> | 已套利次数: ${arbCountText}</span>
              <span> | 市场1剩余/已用: ${market1RemainingText}/${market1ConsumedText}</span>
              <span> | 市场2剩余/已用: ${market2RemainingText}/${market2ConsumedText}</span>
            </div>
          `;
          arbResultDiv.style.display = 'block';
        }

        if (status === 'finished') {
          evt.close();
        }
      } else {
        // 单个监控数据显示
        obDiv.innerHTML = `
          <div>Ask: ${d.ask ? d.ask.value : '-'} @ ${d.ask ? d.ask.quantity : '-'} </div>
          <div>Bid: ${d.bid ? d.bid.value : '-'} @ ${d.bid ? d.bid.quantity : '-'} </div>
        `;
      }
    } catch (err) {
      obDiv.textContent = '解析数据出错: ' + err.message;
    }
  };

  evt.onerror = () => {
    if (statusSpan.textContent !== 'finished') {
      statusSpan.textContent = 'disconnected';
    }
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
  
  const type2 = document.getElementById('arb-type-2').value;
  const market2 = document.getElementById('arb-market-2').value;
  
  const freq = Number(document.getElementById('arb-freq').value) || 5;
  const min_spread = Number(document.getElementById('arb-min-spread').value) || 0.01;
  const max_arb_ratio = Number(document.getElementById('arb-max-ratio').value) || 1.0;
  const max_arb_quantity_input = Number(document.getElementById('arb-max-quantity').value);
  const max_arb_quantity = max_arb_quantity_input > 0 ? max_arb_quantity_input : null;
  const market1_budget = Number(document.getElementById('arb-market1-budget').value);
  const market2_budget = Number(document.getElementById('arb-market2-budget').value);

  if (!(market1_budget > 0) || !(market2_budget > 0)) {
    alert('市场1和市场2的预分配金额必须大于0');
    return;
  }

  const res = await fetch('/api/arbitrage', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      type1, market1,
      type2, market2,
      max_arb_ratio,
      max_arb_quantity,
      market1_budget,
      market2_budget,
      freq,
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
