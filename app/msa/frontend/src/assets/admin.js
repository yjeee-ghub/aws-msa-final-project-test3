// 데이터는 관리자 전용 API에서만 읽고 HTML 문자열로 삽입하지 않는다.
renderHeader();
let dashboardLoading = false;
const dashboardNumber = value => Number.isFinite(Number(value)) && value !== null && value !== undefined
  ? Number(value).toLocaleString('ko-KR') : '—';
function setDashboardText(id, value) { document.getElementById(id).textContent = value; }
function setDashboardStatus(id, label, state) {
  const el = document.getElementById(id);
  el.textContent = label;
  el.className = 'status-pill ' + state;
}
function applyDashboard(data) {
  const db = data.database || {}, monitoring = data.monitoring || {}, deployment = data.deployment || {};
  ['members', 'products', 'orders', 'stock'].forEach(key => {
    setDashboardText(key + 'Count', db.status === 'ok' ? dashboardNumber(db[key]) : '—');
  });
  setDashboardStatus('dbStatus', db.status === 'ok' ? 'DB 집계 연결 정상' : 'DB 확인 불가', db.status === 'ok' ? 'good' : 'warn');
  setDashboardStatus('grafanaStatus', monitoring.grafana === 'ok' ? '정상' : '확인 불가', monitoring.grafana === 'ok' ? 'good' : 'warn');
  setDashboardText('nodesReady', monitoring.metrics === 'ok' ? dashboardNumber(monitoring.nodesReady) : '—');
  setDashboardText('podsReady', monitoring.metrics === 'ok' ? dashboardNumber(monitoring.podsReady) : '—');
  const sync = deployment.status === 'ok' ? (deployment.sync || 'Unknown') : '확인 불가';
  const health = deployment.status === 'ok' ? (deployment.health || 'Unknown') : '확인 불가';
  setDashboardStatus('syncStatus', sync, sync === 'Synced' ? 'good' : 'warn');
  setDashboardStatus('healthStatus', health, health === 'Healthy' ? 'good' : 'warn');
  setDashboardText('appRevision', deployment.revision ? deployment.revision.slice(0, 7) : '—');
  const allOk = db.status === 'ok' && monitoring.grafana === 'ok' && monitoring.metrics === 'ok'
    && sync === 'Synced' && health === 'Healthy';
  setDashboardStatus('overallStatus', allOk ? '조회한 항목 정상' : '확인할 항목 있음', allOk ? 'good' : 'warn');
  const checked = new Date(data.checkedAt);
  setDashboardText('checkedAt', Number.isNaN(checked.getTime()) ? '최근 확인 —' : '최근 확인 ' + checked.toLocaleTimeString('ko-KR'));
}
async function loadDashboard() {
  if (dashboardLoading) return;
  dashboardLoading = true;
  const button = document.getElementById('refreshDashboard');
  const message = document.getElementById('dashboardMessage');
  button.disabled = true; message.hidden = true; message.style.display = 'none';
  try {
    const data = await apiRequest('/member-service/member/admin/summary', { method: 'GET', cache: 'no-store' });
    applyDashboard(data);
  } catch (error) {
    applyDashboard({});
    setDashboardStatus('overallStatus', '조회 실패', 'warn');
    message.hidden = false;
    showMessage('dashboardMessage', error.message || '운영 정보를 가져오지 못했습니다.', 'error');
  } finally { button.disabled = false; dashboardLoading = false; }
}
document.getElementById('refreshDashboard').addEventListener('click', loadDashboard);
loadDashboard();
setInterval(() => { if (!document.hidden) loadDashboard(); }, 60000);

const adminElement = id => document.getElementById(id);
const adminViews = {
  members: { title: '전체 회원', intro: '가입한 계정의 아이디, 닉네임과 권한을 확인합니다.', columns: ['회원 번호', '아이디', '닉네임', '권한'] },
  orders: { title: '접수 주문', intro: '완료, 처리 중, 실패를 포함한 전체 주문 기록입니다.', columns: ['주문 번호', '회원', '상품', '수량', '상태'] },
  products: { title: '상품 및 재고 관리', intro: '상품을 검색하고 현재 판매 가능한 재고를 바로 수정할 수 있습니다.', columns: ['상품', '카테고리', '가격', '현재 재고', '재고 수정'] },
  stock: { title: '재고 현황', intro: '판매 가능한 재고가 적은 상품부터 표시합니다.', columns: ['상품', '카테고리', '가격', '현재 재고', '재고 수정'] }
};
const orderLabels = {
  ORDERED: '주문 완료', PENDING: '재고 확인 중', CONFIRMING: '주문 확정 중',
  COMPENSATING: '재고 복구 중', FAILED: '실패·재고 해제 완료', CANCELED: '취소'
};
let activeView;
let activePage = 0;
let listGeneration = 0;
let inventoryRows = [];

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function isInventory(view) { return view === 'products' || view === 'stock'; }

function listMessage(text, error = false) {
  const message = adminElement('adminListMessage');
  message.textContent = text;
  message.classList.toggle('is-error', error);
}

function reflectStock(product, cell) {
  const quantity = product.stockQuantity;
  const badge = element('span', quantity === 0 ? '품절' : quantity < 6 ? '재고 부족' : '판매 중',
    'status-pill ' + (quantity < 6 ? 'warn' : 'good'));
  cell.replaceChildren(element('strong', dashboardNumber(quantity) + '개', 'stock-value'), badge);
}

function inventoryRow(product, generation) {
  const row = element('tr');
  const productCell = element('th');
  productCell.scope = 'row';
  const link = element('a', product.name);
  link.href = '/product-create.html?id=' + encodeURIComponent(product.id);
  productCell.append(link, element('span', '#' + product.id, 'item-id'));
  const stock = element('td', undefined, 'stock-cell');
  reflectStock(product, stock);

  const editCell = element('td');
  const form = element('form', undefined, 'stock-form');
  const input = element('input');
  input.type = 'number';
  input.min = '0';
  input.max = '2147483647';
  input.step = '1';
  input.required = true;
  input.value = product.stockQuantity;
  input.setAttribute('aria-label', product.name + ' 재고 수량');
  const save = element('button', '저장', 'btn btn-light');
  save.type = 'submit';
  save.disabled = true;
  form.append(input, save);
  input.addEventListener('input', () => {
    save.disabled = !input.validity.valid || input.valueAsNumber === product.stockQuantity;
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (save.disabled || !input.validity.valid) return;
    const stockQuantity = input.valueAsNumber;
    input.disabled = save.disabled = true;
    try {
      const updated = await apiRequest('/product-service/product/' + encodeURIComponent(product.id) + '/stock', {
        method: 'PATCH',
        body: JSON.stringify({ expectedStockQuantity: product.stockQuantity, stockQuantity })
      });
      product.stockQuantity = updated.stockQuantity;
      input.value = updated.stockQuantity;
      reflectStock(product, stock);
      if (generation === listGeneration) listMessage(product.name + ' 재고를 ' + dashboardNumber(updated.stockQuantity) + '개로 저장했습니다.');
      loadDashboard();
    } catch (error) {
      if (generation !== listGeneration) return;
      if (error.status === 409) {
        const refresh = openAdminList(activeView);
        const refreshGeneration = listGeneration;
        if (await refresh && refreshGeneration === listGeneration) {
          listMessage('재고가 변경되어 최신 목록을 불러왔습니다. 현재 수량을 확인한 뒤 다시 저장해주세요.', true);
        }
      } else {
        listMessage(error.message || '재고를 저장하지 못했습니다.', true);
      }
    } finally {
      input.disabled = false;
      save.disabled = !input.validity.valid || input.valueAsNumber === product.stockQuantity;
    }
  });
  editCell.append(form);
  row.append(productCell, element('td', product.category || '—'), element('td', formatPrice(product.price)), stock, editCell);
  return row;
}

function renderAdminTable(view, items) {
  const target = adminElement('adminTable');
  if (!items.length) {
    target.replaceChildren(element('p', '표시할 항목이 없습니다.', 'admin-list-empty'));
    return;
  }
  const table = element('table');
  const heading = element('tr');
  for (const title of adminViews[view].columns) {
    const cell = element('th', title);
    cell.scope = 'col';
    heading.append(cell);
  }
  table.createTHead().append(heading);
  const body = table.createTBody();
  for (const item of items) {
    if (isInventory(view)) {
      body.append(inventoryRow(item, listGeneration));
    } else {
      const row = element('tr');
      const values = view === 'members'
        ? ['#' + item.id, item.loginId, item.nickname, item.role === 'ADMIN' ? '관리자' : '일반 회원']
        : ['#' + item.id, item.nickname || '—', item.product || '—', dashboardNumber(item.quantity) + '개', orderLabels[item.status] || '—'];
      for (const value of values) row.append(element('td', value ?? '—'));
      body.append(row);
    }
  }
  target.replaceChildren(table);
}

function renderInventory() {
  if (!isInventory(activeView)) return;
  const term = adminElement('inventorySearch').value.trim().toLowerCase();
  const state = adminElement('inventoryFilter').value;
  const items = inventoryRows.filter(product => {
    const quantity = product.stockQuantity;
    const matchesState = state === 'all' || (state === 'out' ? quantity === 0 : quantity > 0 && quantity < 6);
    return matchesState && (product.name + ' ' + (product.category || '')).toLowerCase().includes(term);
  });
  if (activeView === 'stock') items.sort((a, b) => a.stockQuantity - b.stockQuantity || b.id - a.id);
  renderAdminTable(activeView, items);
}

async function openAdminList(view, page = 0, focus = false) {
  const generation = ++listGeneration;
  if (activeView !== view) {
    adminElement('inventorySearch').value = '';
    adminElement('inventoryFilter').value = 'all';
  }
  activeView = view;
  activePage = page;
  for (const button of adminElement('storeSummary').querySelectorAll('button[data-view]')) {
    button.setAttribute('aria-expanded', String(button.dataset.view === view));
  }
  adminElement('adminList').hidden = false;
  adminElement('adminListTitle').textContent = adminViews[view].title;
  adminElement('adminListIntro').textContent = adminViews[view].intro;
  adminElement('inventoryControls').hidden = !isInventory(view);
  adminElement('adminPagination').hidden = true;
  adminElement('adminTable').replaceChildren();
  inventoryRows = [];
  listMessage('목록을 불러오는 중입니다.');
  if (focus) adminElement('adminListTitle').focus();
  try {
    const url = isInventory(view)
      ? '/product-service/product/list'
      : '/member-service/member/admin/' + view + '?page=' + page;
    const data = await apiRequest(url, { cache: 'no-store' });
    if (generation !== listGeneration) return;
    listMessage('');
    if (isInventory(view)) {
      inventoryRows = data;
      renderInventory();
    } else {
      renderAdminTable(view, data.items);
      adminElement('adminPagination').hidden = page === 0 && !data.hasNext;
      adminElement('adminPrev').disabled = page === 0;
      adminElement('adminNext').disabled = !data.hasNext;
      adminElement('adminPage').textContent = (page + 1) + ' 페이지';
    }
    return true;
  } catch (error) {
    if (generation === listGeneration) listMessage(error.message || '목록을 불러오지 못했습니다.', true);
  }
}

adminElement('storeSummary').addEventListener('click', event => {
  const button = event.target.closest('button[data-view]');
  if (button) openAdminList(button.dataset.view, 0, true);
});
adminElement('closeAdminList').addEventListener('click', () => {
  const button = adminElement('storeSummary').querySelector('[aria-expanded="true"]');
  button?.setAttribute('aria-expanded', 'false');
  listGeneration++;
  activeView = undefined;
  inventoryRows = [];
  adminElement('adminTable').replaceChildren();
  adminElement('adminList').hidden = true;
  button?.focus();
});
adminElement('inventorySearch').addEventListener('input', renderInventory);
adminElement('inventoryFilter').addEventListener('change', renderInventory);
adminElement('adminPrev').addEventListener('click', () => openAdminList(activeView, activePage - 1));
adminElement('adminNext').addEventListener('click', () => openAdminList(activeView, activePage + 1));
