/**
 * GPU 推薦助手 — 前端互動邏輯
 */

const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const btnSend = document.getElementById('btn-send');
const welcomeMsg = document.getElementById('welcome-msg');

let isLoading = false;

// ===== 訊息操作 =====

function addMessage(role, content, recommendations = []) {
  // 隱藏歡迎訊息
  if (welcomeMsg) welcomeMsg.style.display = 'none';

  const div = document.createElement('div');
  div.className = `message ${role}`;

  const avatar = role === 'user' ? '👤' : '🤖';
  
  div.innerHTML = `
    <div class="msg-avatar">${avatar}</div>
    <div class="msg-content">
      <div class="msg-bubble">${escapeHtml(content)}</div>
      ${recommendations.length > 0 ? renderRecommendations(recommendations) : ''}
    </div>
  `;

  chatMessages.appendChild(div);
  scrollToBottom();
}

function renderRecommendations(recs) {
  if (!recs || recs.length === 0) return '';

  // 計算最大 CP 值（用於 CP Bar 比例）
  const maxCP = Math.max(...recs.map(r => r.cp || r.CP || 0));
  // alternative 卡片的排序（非目標卡）
  let altIdx = 0;

  const cards = recs.map((rec) => {
    const isTarget = rec.is_target === true;
    const cp = (rec.cp || rec.CP || 0).toFixed(4);
    const score = (rec.score || 0).toLocaleString();
    const price = (rec.price || 0).toLocaleString();
    const cpPct = maxCP > 0 ? ((rec.cp || rec.CP || 0) / maxCP * 100).toFixed(1) : 0;
    const diff = rec.price_diff_pct || '';
    const diffClass = diff.startsWith('+') ? 'positive' : diff.startsWith('-') ? 'negative' : 'neutral';
    const gpuName = rec.name || rec.pure_chipset || '';
    const productName = rec.product || '';

    let rankBadge;
    if (isTarget) {
      rankBadge = `<div class="rec-rank" style="background:linear-gradient(135deg,#f97316,#fb923c);color:white;font-size:10px;width:36px;border-radius:6px;">目標卡</div>`;
    } else {
      altIdx++;
      const rankClass = `rank-${altIdx}`;
      rankBadge = `<div class="rec-rank ${rankClass}">#${altIdx}</div>`;
    }

    const borderStyle = isTarget ? 'border-color: rgba(249,115,22,0.4);' : '';

    return `
      <div class="rec-card" data-date="${rec.date || ''}" style="${borderStyle}">
        ${rankBadge}
        <div class="rec-gpu-name">${escapeHtml(gpuName)}</div>
        <div class="rec-product-name">${escapeHtml(productName.substring(0, 60))}${productName.length > 60 ? '...' : ''}</div>
        <div class="rec-stats">
          <div class="rec-stat-row">
            <span class="rec-stat-label">💰 售價</span>
            <span class="rec-stat-value">$${price}
              ${diff ? `<span class="rec-price-diff ${diffClass}">${diff}</span>` : ''}
            </span>
          </div>
          <div class="rec-stat-row">
            <span class="rec-stat-label">⚡ 跑分</span>
            <span class="rec-stat-value">${score}</span>
          </div>
          <div class="rec-stat-row">
            <span class="rec-stat-label">🏆 CP 值</span>
            <span class="rec-stat-value" style="color: ${isTarget ? '#f97316' : '#6366f1'};">${cp}</span>
          </div>
        </div>
        <div class="rec-cp-bar">
          <div class="rec-cp-fill" style="width: ${cpPct}%; ${isTarget ? 'background:linear-gradient(135deg,#f97316,#fb923c);' : ''}"></div>
        </div>
      </div>
    `;
  });

  return `<div class="recommendations-grid">${cards.join('')}</div>`;
}


function addTypingIndicator() {
  const div = document.createElement('div');
  div.className = 'message assistant';
  div.id = 'typing-indicator';
  div.innerHTML = `
    <div class="msg-avatar">🤖</div>
    <div class="msg-content">
      <div class="typing-indicator">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
    </div>
  `;
  chatMessages.appendChild(div);
  scrollToBottom();
}

function removeTypingIndicator() {
  const indicator = document.getElementById('typing-indicator');
  if (indicator) indicator.remove();
}

function scrollToBottom() {
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

// ===== 事件處理 =====

async function sendMessage(event) {
  if (event) event.preventDefault();
  
  const message = chatInput.value.trim();
  if (!message || isLoading) return;

  // 顯示使用者訊息
  addMessage('user', message);
  chatInput.value = '';
  autoResize(chatInput);

  // 開始 loading
  setLoading(true);
  addTypingIndicator();

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    });

    const data = await response.json();
    removeTypingIndicator();

    if (!response.ok) {
      addMessage('assistant', `抱歉，發生錯誤：${data.error || '請稍後再試'}`);
      return;
    }

    addMessage(
      'assistant',
      data.assistant_message || '無法生成回覆，請稍後再試。',
      data.recommendations || []
    );

    // 更新 DB 狀態
    if (data.latest_date) {
      updateDbStatusDisplay(data.latest_date);
    }

  } catch (err) {
    removeTypingIndicator();
    addMessage('assistant', `網路錯誤：${err.message}\n\n請確認後端伺服器是否正常運行。`);
  } finally {
    setLoading(false);
  }
}

function sendQuickPrompt(prompt) {
  chatInput.value = prompt;
  sendMessage(null);
}

function handleKeyDown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendMessage(null);
  }
}

function autoResize(textarea) {
  textarea.style.height = 'auto';
  textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
}

function setLoading(loading) {
  isLoading = loading;
  btnSend.disabled = loading;
  chatInput.disabled = loading;
  document.getElementById('send-icon').textContent = loading ? '…' : '↑';
}

// ===== 更新資料庫 =====

async function updateDatabase(force = false) {
  const btn = document.getElementById('btn-update-db');
  const icon = document.getElementById('update-icon');
  const text = document.getElementById('update-text');

  btn.disabled = true;
  icon.style.animation = 'spin 1s linear infinite';
  text.textContent = '更新中...';

  // 新增 spin keyframe（若未建立）
  if (!document.getElementById('spin-style')) {
    const style = document.createElement('style');
    style.id = 'spin-style';
    style.textContent = '@keyframes spin { from { display: inline-block; transform: rotate(0deg); } to { transform: rotate(360deg); } }';
    document.head.appendChild(style);
  }

  showToast('info', '🔄 正在更新資料庫，這可能需要幾分鐘...');

  try {
    const response = await fetch('/api/update-db', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    });

    const data = await response.json();

    if (data.status === 'success') {
      showToast('success', `✅ ${data.message || '資料庫更新成功！'}`);
      // 重新取得 DB meta，首次建立時解鎖 UI
      await refreshDbMeta();
      onDbBecameReady();
    } else if (data.status === 'skipped') {
      showToast('info', `ℹ️ ${data.reason}`);
    } else {
      showToast('error', `❌ 更新失敗：${data.reason || '未知錯誤'}`);
    }
  } catch (err) {
    showToast('error', `❌ 連線失敗：${err.message}`);
  } finally {
    btn.disabled = false;
    icon.style.animation = '';
    text.textContent = '更新資料庫';
  }
}

async function refreshDbMeta() {
  try {
    const response = await fetch('/api/db-meta');
    const meta = await response.json();
    
    const dot = document.getElementById('db-status-dot');
    const statusText = document.getElementById('db-status-text');
    
    if (meta.latest_date) {
      dot.classList.remove('empty');
      statusText.textContent = `共 ${meta.count} 筆｜${meta.latest_date}`;
    } else {
      dot.classList.add('empty');
      statusText.textContent = '尚無資料';
    }
  } catch (err) {
    console.error('無法取得 DB meta:', err);
  }
}

function updateDbStatusDisplay(date) {
  const statusText = document.getElementById('db-status-text');
  if (statusText && date) {
    const current = statusText.textContent;
    if (!current.includes(date)) {
      // 保持現有筆數，只更新日期標記
    }
  }
}

function onDbBecameReady() {
  // 移除 DB 未就緒的橘色橫幅
  const banner = document.getElementById('db-init-banner');
  if (banner) banner.remove();

  // 解除輸入框 disabled
  const input = document.getElementById('chat-input');
  const sendBtn = document.getElementById('btn-send');
  if (input && input.disabled) {
    input.disabled = false;
    input.style.opacity = '';
    input.style.cursor = '';
    input.placeholder = '輸入您的預算（例：預算 15000）或目標顯卡型號...';
  }
  if (sendBtn && sendBtn.disabled) {
    sendBtn.disabled = false;
    sendBtn.style.opacity = '';
    sendBtn.style.cursor = '';
  }

  // 重新載入頁面讓快速提示按鈕出現（簡單可靠）
  if (!document.querySelector('.quick-prompts')) {
    window.location.reload();
  }
}

// ===== Toast 通知 =====

function showToast(type, message, duration = 4000) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// ===== 工具函式 =====

function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.appendChild(document.createTextNode(String(text)));
  return div.innerHTML;
}

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', () => {
  chatInput.focus();
  // 定期更新 DB 狀態
  setInterval(refreshDbMeta, 60000);

  // DB 瀏覽初始化
  loadDbBrowse();
  attachDbBrowseEvents();
});


// ===== DB 瀏覽 =====

// 文字欄位預設升序，數值欄位預設降序
const DB_SORT_DEFAULT_ORDER = {
  chipset: 'asc', product: 'asc', pure_chipset: 'asc',
  price: 'desc', score: 'desc', CP: 'desc',
};

// 所有排序欄位清單
const DB_ALL_SORT_COLS = ['chipset', 'product', 'price', 'pure_chipset', 'score', 'CP'];

let dbBrowseSort = 'CP';
let dbBrowseOrder = 'desc';
let dbBrowsePage = 1;
let dbBrowseTotalPages = 1;
let dbBrowseSearchTimer = null;
let dbBrowsePriceTimer = null;

async function loadDbBrowse(opts = {}) {
  const tbody = document.getElementById('db-tbody');
  if (!tbody) return;

  // 讀取當前各控制元件的值（未傳入時用全域狀態/DOM）
  const search  = opts.search  !== undefined ? opts.search  : (document.getElementById('db-search-input')?.value?.trim() || '');
  const sort    = opts.sort    !== undefined ? opts.sort    : dbBrowseSort;
  const order   = opts.order   !== undefined ? opts.order   : dbBrowseOrder;
  const page    = opts.page    !== undefined ? opts.page    : dbBrowsePage;
  const priceMin = opts.priceMin !== undefined ? opts.priceMin : (document.getElementById('db-price-min')?.value?.trim() || '');
  const priceMax = opts.priceMax !== undefined ? opts.priceMax : (document.getElementById('db-price-max')?.value?.trim() || '');

  // 更新全域狀態
  dbBrowseSort  = sort;
  dbBrowseOrder = order;
  dbBrowsePage  = page;

  tbody.innerHTML = '<tr><td colspan="6" class="db-empty">載入中...</td></tr>';

  const params = new URLSearchParams({ sort, order, page });
  if (search)   params.set('search', search);
  if (priceMin) params.set('price_min', priceMin);
  if (priceMax) params.set('price_max', priceMax);

  try {
    const res = await fetch('/api/db-browse?' + params.toString());
    const data = await res.json();

    if (data.error) {
      tbody.innerHTML = `<tr><td colspan="6" class="db-empty">⚠️ 無法載入資料：${escapeHtml(data.error)}</td></tr>`;
      return;
    }

    dbBrowseTotalPages = data.total_pages || 1;
    dbBrowsePage = data.page || 1;
    renderDbTable(data.rows || [], data.total || 0, data.latest_date || '', data.page || 1, data.total_pages || 1);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="db-empty">⚠️ 連線失敗：${escapeHtml(err.message)}</td></tr>`;
  }
}

function renderDbTable(rows, total, latestDate, page, totalPages) {
  const tbody    = document.getElementById('db-tbody');
  const countEl  = document.getElementById('db-count');
  const dateBadge = document.getElementById('db-browser-date');
  const pageInfo  = document.getElementById('db-page-info');
  const prevBtn   = document.getElementById('db-page-prev');
  const nextBtn   = document.getElementById('db-page-next');

  // 日期 badge
  if (dateBadge && latestDate) {
    dateBadge.textContent = `資料日期：${latestDate}`;
  }

  // 排序箭頭：更新所有六欄
  DB_ALL_SORT_COLS.forEach(col => {
    const th    = document.getElementById(`th-${col}`);
    const arrow = document.getElementById(`arrow-${col}`);
    if (!th || !arrow) return;
    if (col === dbBrowseSort) {
      th.classList.add('active');
      arrow.textContent = dbBrowseOrder === 'desc' ? '▾' : '▴';
    } else {
      th.classList.remove('active');
      arrow.textContent = '';
    }
  });

  // 筆數
  if (countEl) {
    const hasFilter = (document.getElementById('db-search-input')?.value?.trim() ||
                       document.getElementById('db-price-min')?.value?.trim()   ||
                       document.getElementById('db-price-max')?.value?.trim());
    countEl.textContent = hasFilter ? `篩選結果：${total} 筆` : `共 ${total} 筆`;
  }

  // 分頁列
  if (pageInfo) pageInfo.textContent = `第 ${page} 頁，共 ${totalPages} 頁`;
  if (prevBtn)  prevBtn.disabled  = (page <= 1);
  if (nextBtn)  nextBtn.disabled  = (page >= totalPages);

  // 無資料
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="db-empty">查無符合條件的資料</td></tr>';
    return;
  }

  // 渲染列
  const html = rows.map(r => {
    const price      = r.price != null ? `$${Number(r.price).toLocaleString()}` : '—';
    const score      = r.score != null ? Number(r.score).toLocaleString() : '—';
    const cp         = r.CP   != null ? r.CP.toFixed(4) : '—';
    const chipset    = escapeHtml(r.chipset     || '—');
    const product    = escapeHtml(r.product     || '—');
    const pureChipset = escapeHtml(r.pure_chipset || '—');

    return `
      <tr>
        <td class="db-td db-td-chipset">${chipset}</td>
        <td class="db-td db-td-product">${product}</td>
        <td class="db-td db-td-price">${price}</td>
        <td class="db-td db-td-pure-chipset">${pureChipset}</td>
        <td class="db-td db-td-score">${score}</td>
        <td class="db-td db-td-cp">${cp}</td>
      </tr>`;
  }).join('');

  tbody.innerHTML = html;
}

function dbChangePage(delta) {
  const newPage = dbBrowsePage + delta;
  if (newPage < 1 || newPage > dbBrowseTotalPages) return;
  loadDbBrowse({ page: newPage });
}

function attachDbBrowseEvents() {
  // 搜尋框 debounce
  const searchInput = document.getElementById('db-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      clearTimeout(dbBrowseSearchTimer);
      dbBrowseSearchTimer = setTimeout(() => {
        loadDbBrowse({ page: 1 });
      }, 300);
    });
  }

  // 售價範圍 debounce
  const priceMin = document.getElementById('db-price-min');
  const priceMax = document.getElementById('db-price-max');
  const priceClear = document.getElementById('db-price-clear');

  const onPriceInput = () => {
    clearTimeout(dbBrowsePriceTimer);
    dbBrowsePriceTimer = setTimeout(() => {
      loadDbBrowse({ page: 1 });
    }, 400);
  };

  if (priceMin) priceMin.addEventListener('input', onPriceInput);
  if (priceMax) priceMax.addEventListener('input', onPriceInput);

  if (priceClear) {
    priceClear.addEventListener('click', () => {
      if (priceMin) priceMin.value = '';
      if (priceMax) priceMax.value = '';
      loadDbBrowse({ page: 1 });
    });
  }

  // 排序欄位標頭點擊（六欄）
  document.querySelectorAll('.db-th-sort').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      if (!col) return;

      if (dbBrowseSort === col) {
        // 同欄位：切換升降序
        dbBrowseOrder = dbBrowseOrder === 'desc' ? 'asc' : 'desc';
      } else {
        // 換新欄位：按欄位類型決定預設排序方向
        dbBrowseSort  = col;
        dbBrowseOrder = DB_SORT_DEFAULT_ORDER[col] || 'desc';
      }

      loadDbBrowse({ sort: dbBrowseSort, order: dbBrowseOrder, page: 1 });
    });
  });
}


