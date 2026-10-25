/**
 * OmniSupply Frontend Application Logic
 */

document.addEventListener('DOMContentLoaded', () => {
  let selectedAgent = 'supervisor';

  const agentButtons = document.querySelectorAll('.agent-btn');
  const queryInput = document.getElementById('query-input');
  const sendBtn = document.getElementById('send-btn');
  const placeholderView = document.getElementById('placeholder-view');
  const resultView = document.getElementById('result-view');
  const agentBadge = document.getElementById('res-agent-badge');
  const execTimeBadge = document.getElementById('res-exec-time');
  const insightsList = document.getElementById('res-insights-list');
  const recList = document.getElementById('res-rec-list');
  const metricsSection = document.getElementById('res-metrics-section');
  const metricsJson = document.getElementById('res-metrics-json');
  const chips = document.querySelectorAll('.chip');
  const statusPill = document.getElementById('system-status-pill');
  const statusText = document.getElementById('system-status-text');

  // Agent selector switching
  agentButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      agentButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      selectedAgent = btn.getAttribute('data-agent');
    });
  });

  // Preset prompt chips
  chips.forEach(chip => {
    chip.addEventListener('click', () => {
      queryInput.value = chip.getAttribute('data-prompt');
      executeCurrentQuery();
    });
  });

  // Enter key in input
  queryInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      executeCurrentQuery();
    }
  });

  sendBtn.addEventListener('click', executeCurrentQuery);

  async function executeCurrentQuery() {
    const query = queryInput.value.trim();
    if (!query) return;

    // Loading State
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<span>Processing...</span><span class="pulse-dot"></span>';

    try {
      const response = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query,
          agent: selectedAgent
        })
      });

      if (!response.ok) {
        throw new Error(`API error (${response.status})`);
      }

      const data = await response.json();
      renderResult(data);
    } catch (err) {
      renderError(err.message);
    } finally {
      sendBtn.disabled = false;
      sendBtn.innerHTML = '<span>Run Query</span><span>→</span>';
    }
  }

  function renderResult(data) {
    placeholderView.style.display = 'none';
    resultView.style.display = 'flex';

    agentBadge.textContent = `Agent: ${data.agent_name || selectedAgent}`;
    execTimeBadge.textContent = `Execution: ${data.execution_time_ms ? data.execution_time_ms.toFixed(1) + 'ms' : 'Ready'}`;

    // Render Insights
    insightsList.innerHTML = '';
    const insights = data.insights || [];
    if (insights.length > 0) {
      insights.forEach(insight => {
        const item = document.createElement('div');
        item.className = 'insight-item';
        item.textContent = `💡 ${insight}`;
        insightsList.appendChild(item);
      });
    } else {
      insightsList.innerHTML = '<div class="insight-item">Query completed successfully with no additional anomalies found.</div>';
    }

    // Render Recommendations
    recList.innerHTML = '';
    const recs = data.recommendations || [];
    if (recs.length > 0) {
      recs.forEach(rec => {
        const item = document.createElement('div');
        item.className = 'rec-item';
        item.textContent = `🎯 ${rec}`;
        recList.appendChild(item);
      });
    } else {
      recList.innerHTML = '<div class="rec-item">Continue standard supply chain schedule monitoring.</div>';
    }

    // Render Metrics
    if (data.metrics && Object.keys(data.metrics).length > 0) {
      metricsSection.style.display = 'block';
      metricsJson.textContent = JSON.stringify(data.metrics, null, 2);
    } else {
      metricsSection.style.display = 'none';
    }
  }

  function renderError(message) {
    placeholderView.style.display = 'none';
    resultView.style.display = 'flex';
    agentBadge.textContent = 'Agent: Error';
    execTimeBadge.textContent = '';
    insightsList.innerHTML = `<div class="insight-item" style="border-color: #f43f5e; color: #fecdd3;">⚠️ ${message}</div>`;
    recList.innerHTML = '<div class="rec-item">Check terminal logs and backend server status.</div>';
    metricsSection.style.display = 'none';
  }

  // Check health on load
  async function checkHealth() {
    try {
      const res = await fetch('/api/health');
      if (res.ok) {
        const data = await res.json();
        if (data.status === 'ok') {
          statusText.textContent = 'Agents Operational';
        }
      }
    } catch {
      statusText.textContent = 'Offline';
    }
  }

  checkHealth();
});
