const API_BASE = '';
const PLACEHOLDER_IMAGE = '/assets/product-placeholder.svg';

// 상품명과 닉네임을 HTML이 아닌 텍스트로 표시
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, function (character) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character];
  });
}

function saveAuth(data) {
  localStorage.setItem('auth', JSON.stringify(data));
}

function getAuth() {
  const raw = localStorage.getItem('auth');
  try { return raw ? JSON.parse(raw) : null; } catch { return null; }
}

function clearAuth() {
  localStorage.removeItem('auth');
}

function getToken() {
  const auth = getAuth();
  return auth ? auth.token : null;
}

function toggleHeaderMenus(auth) {
  document.querySelectorAll('[data-guest-only]').forEach(function (el) {
    el.style.display = auth ? 'none' : '';
  });

  document.querySelectorAll('[data-auth-only]').forEach(function (el) {
    el.style.display = auth ? '' : 'none';
  });
}

function renderHeader() {
  // 메뉴 표시는 편의를 위한 것이며 실제 권한은 Gateway와 Nginx에서 검사한다.
  const nav = document.querySelector('.nav');
  if (nav && !nav.querySelector('[data-cart-link]')) {
    nav.insertAdjacentHTML('afterbegin', '<a class="btn btn-light" data-cart-link href="/cart.html">장바구니</a><a class="btn btn-light" data-auth-only href="/orders.html">주문 내역</a><a class="btn btn-light" data-admin-only style="display:none" href="/admin.html">관리자</a>');
  }
  const auth = getAuth();
  const userBox = document.getElementById('userBox');

  toggleHeaderMenus(auth);
  document.querySelectorAll('[data-admin-only]').forEach(el => {
    el.style.display = auth && auth.role === 'ADMIN' ? '' : 'none';
  });

  if (!userBox) {
    return;
  }

  if (auth) {
    userBox.innerHTML = `
      <div class="user-chip">
        <span class="user-chip-label">${escapeHtml(auth.nickname || auth.name || auth.loginId || auth.email || '회원')}님</span>
        <button class="btn btn-dark" id="logoutBtn" type="button">로그아웃</button>
      </div>
    `;
    const logoutBtn = document.getElementById('logoutBtn');
    logoutBtn.addEventListener('click', async function () {
      try {
        await apiRequest('/member-service/member/logout', { method: 'POST' });
      } catch {
        alert('로그아웃 요청에 실패했습니다. 다시 시도해주세요.');
        return;
      }
      clearAuth();
      window.location.href = '/';
    });
  } else {
    userBox.innerHTML = '';
  }
}

function showMessage(targetId, message, type) {
  const target = document.getElementById(targetId);
  if (!target) {
    return;
  }
  target.className = `message ${type}`;
  target.textContent = message;
  target.style.display = 'block';
}

async function apiRequest(url, options = {}) {
  const headers = options.headers || {};
  const token = getToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (!headers['Content-Type'] && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers
  });

  if (!response.ok) {
    if (response.status === 401) throw new Error('로그인이 만료되었습니다. 다시 로그인해주세요.');
    if (response.status === 403) throw new Error('접근 권한이 없습니다.');
    const text = await response.text();
    let detail = text;
    try { const data = JSON.parse(text); detail = data.message || data.error || '요청에 실패했습니다.'; } catch {}

    const error = new Error(detail.length < 200 ? detail : '요청에 실패했습니다. 재고와 입력값을 확인해주세요.');
    error.status = response.status;
    try { error.data = JSON.parse(text); } catch {}
    throw error;
  }

  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return response.json();
  }
  return response.text();
}

function getImageUrl(url) {
  return url || PLACEHOLDER_IMAGE;
}

function formatPrice(value) {
  return `${Number(value || 0).toLocaleString()}원`;
}

function getProductDetailUrl(productId) {
  return `/product-detail.html?id=${encodeURIComponent(productId)}`;
}

function goToProductDetail(productId) {
  window.location.href = getProductDetailUrl(productId);
}

window.goToProductDetail = goToProductDetail;

function getQueryParam(name) {
  const params = new URLSearchParams(window.location.search);
  return params.get(name);
}

function buildStockBadge(stockQuantity) {
  if (stockQuantity < 1) {
    return '<span class="stock-badge soldout">품절</span>';
  }
  if (stockQuantity < 6) {
    return '<span class="stock-badge limited">수량한정</span>';
  }
  return '<span class="stock-badge normal">판매중</span>';
}

async function loadProducts() {
  const productList = document.getElementById('productList');
  if (!productList) {
    return;
  }

  try {
    const products = await apiRequest('/product-service/product/list', { method: 'GET', headers: {} });
    // 프록시 오류로 HTML 등이 반환돼도 상품 개수로 잘못 표시하지 않음
    if (!Array.isArray(products)) {
      throw new Error('상품 목록 응답 형식이 올바르지 않습니다.');
    }
    const countEl = document.getElementById('productCount');
    if (countEl) {
      countEl.textContent = `총 ${products.length}개의 상품`;
    }

    if (!products.length) {
      productList.innerHTML = '<div class="empty">등록된 상품이 없습니다. 첫 상품을 등록해보세요.</div>';
      return;
    }

    productList.innerHTML = products.map(function (product) {
      return `
        <a class="card card-link" href="${escapeHtml(getProductDetailUrl(product.id))}">
          <div class="card-image-wrap">
            <img src="${escapeHtml(getImageUrl(product.imageUrl))}" alt="${escapeHtml(product.name)}" loading="lazy" onerror="this.onerror=null;this.src='/assets/product-placeholder.svg'">
            ${buildStockBadge(product.stockQuantity)}
          </div>
          <div class="card-body">
            <div class="card-meta-row">
              <span class="card-meta">${escapeHtml(product.category || '전체 카테고리')}</span>
            </div>
            <div class="card-title">${escapeHtml(product.name)}</div>
            <div class="card-price">${formatPrice(product.price)}</div>
            <div class="card-sub">재고 ${escapeHtml(product.stockQuantity)}개</div>
            <div class="card-description">${escapeHtml(product.description || '등록된 상품 설명이 없습니다.')}</div>
          </div>
        </a>
      `;
    }).join('');
  } catch (error) {
    const countEl = document.getElementById('productCount');
    if (countEl) {
      countEl.textContent = '목록을 확인해주세요';
    }
    productList.innerHTML = '<div class="empty">상품 목록을 불러오지 못했습니다.</div>';
  }
}

function guardLogin(redirectPath) {
  if (!getToken()) {
    alert('로그인 후 이용해주세요.');
    window.location.href = redirectPath || '/login.html';
    return false;
  }
  return true;
}

async function loadProductDetail() {
  const target = document.getElementById('productDetail');
  if (!target) {
    return;
  }

  const productId = getQueryParam('id');
  if (!productId) {
    target.innerHTML = '<div class="empty">상품 정보가 없습니다.</div>';
    return;
  }

  try {
    const product = await apiRequest(`/product-service/product/${encodeURIComponent(productId)}`, { method: 'GET', headers: {} });
    target.innerHTML = `
      <section class="detail-card">
        <div class="detail-image-wrap">
          <img class="detail-image" src="${escapeHtml(getImageUrl(product.imageUrl))}" alt="${escapeHtml(product.name)}" onerror="this.onerror=null;this.src='/assets/product-placeholder.svg'">
        </div>
        <div class="detail-content">
          <div class="detail-category">${escapeHtml(product.category || '전체 카테고리')}</div>
          <h1 class="detail-title">${escapeHtml(product.name)}</h1>
          <div class="detail-price">${formatPrice(product.price)}</div>
          <div class="detail-stock" id="detailStock">재고: ${escapeHtml(product.stockQuantity)}개</div>
          <p class="detail-description">${escapeHtml(product.description || '상품 설명이 없습니다.')}</p>
          <label class="quantity-field" for="productQuantity">수량
            <input id="productQuantity" type="number" min="1" max="${Math.min(999, product.stockQuantity)}" value="1" ${product.stockQuantity < 1 ? 'disabled' : ''}>
          </label>
          <div class="detail-actions">
            <button class="btn btn-primary btn-large" id="purchaseBtn" type="button" ${product.stockQuantity < 1 ? 'disabled' : ''}>장바구니 담기</button>
            <a class="btn btn-light btn-large" href="/">메인으로</a>
          </div>
          <div id="purchaseMessage" style="display:none;"></div>
        </div>
      </section>
    `;

    const purchaseBtn = document.getElementById('purchaseBtn');
    if (purchaseBtn) {
      purchaseBtn.addEventListener('click', async function () {
        if (!guardLogin('/login.html')) {
          return;
        }

        if (product.stockQuantity < 1) {
          showMessage('purchaseMessage', '재고가 부족합니다.', 'error');
          return;
        }

        try {
          const quantity = Number(document.getElementById('productQuantity').value);
          if (!Number.isInteger(quantity) || quantity < 1 || quantity > Math.min(999, product.stockQuantity)) {
            throw new Error('재고 내에서 1~999개를 선택해주세요.');
          }
          addToCart(product, quantity);
          showMessage('purchaseMessage', '장바구니에 담았습니다. 장바구니에서 주문해주세요.', 'success');
        } catch (error) {
          showMessage('purchaseMessage', error.message, 'error');
        }
      });
    }
  } catch (error) {
    target.innerHTML = '<div class="empty">상품 상세 정보를 불러오지 못했습니다.</div>';
  }
}


// 장바구니는 로그인한 계정별로 현재 브라우저에 저장한다.
function cartKey() { return 'syong-cart-' + (getAuth()?.id || 'guest'); }
function readCart() {
  try {
    const cart = JSON.parse(localStorage.getItem(cartKey()) || '[]');
    return Array.isArray(cart) ? cart.filter(item => Number.isSafeInteger(item.id) && item.id > 0
      && Number.isInteger(item.quantity) && item.quantity >= 1 && item.quantity <= 999) : [];
  } catch { return []; }
}
function saveCart(cart) { localStorage.setItem(cartKey(), JSON.stringify(cart)); }
function addToCart(product, quantity) {
  const cart = readCart();
  const item = cart.find(item => item.id === Number(product.id));
  const total = quantity + (item?.quantity || 0);
  if (total > Math.min(999, product.stockQuantity)) throw new Error('장바구니 수량이 재고를 초과합니다.');
  if (item?.requestKey) throw new Error('처리 중인 주문은 주문 내역에서 확인해주세요.');
  if (item) { item.quantity = total; item.price = product.price; item.name = product.name; }
  else cart.push({ id: Number(product.id), name: product.name, price: product.price, quantity });
  saveCart(cart);
}

// 기존 주문 API를 상품별로 호출한다. 성공한 상품만 제거하고 실패한 상품은 보존한다.
async function checkoutCart() {
  const cart = readCart();
  let succeeded = 0;
  const failures = [];
  for (const item of cart) {
    try {
      if (!item.requestKey) {
        item.requestKey = crypto.randomUUID();
        saveCart(readCart().map(row => row.id === item.id ? item : row));
      }
      let order = await apiRequest('/ordering-service/ordering/create', { method: 'POST',
        headers: { 'Idempotency-Key': item.requestKey },
        body: JSON.stringify({ productId: item.id, productCount: item.quantity }) });
      for (let attempt = 0; order.status !== 'ORDERED' && order.status !== 'FAILED' && attempt < 3; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        order = await apiRequest('/ordering-service/ordering/' + order.id, { method: 'GET' });
      }
      if (order.status !== 'ORDERED') {
        const error = new Error(order.status === 'FAILED' ? '주문 실패: 재고 복구 완료. 다시 시도할 수 있습니다.' : '처리 중입니다. 주문 내역에서 확인해주세요.');
        error.data = order; throw error;
      }
      const remaining = readCart().filter(row => row.id !== item.id);
      saveCart(remaining);
      succeeded++;
    } catch (error) {

      if (error.data?.status === 'FAILED') {
        saveCart(readCart().map(row => row.id === item.id ? { ...row, requestKey: undefined } : row));
      }
      failures.push(String(item.name) + ': ' + error.message);
    }
  }
  return { succeeded, failures };
}

function renderCart() {
  const cart = readCart();
  const target = document.getElementById('cartItems');
  target.innerHTML = cart.length ? cart.map(item => `
    <article class="cart-row">
      <a href="${escapeHtml(getProductDetailUrl(item.id))}">${escapeHtml(item.name)}</a>
      <span>${formatPrice(item.price)}</span>
      <label>수량 <input class="cart-quantity" aria-label="${escapeHtml(item.name)} 수량" type="number" min="1" max="999" value="${item.quantity}" data-quantity="${item.id}"></label>
      <strong>${formatPrice(item.price * item.quantity)}</strong>
      <button class="btn btn-light" type="button" data-remove="${item.id}">삭제</button>
    </article>`).join('') : '<div class="empty">장바구니가 비어 있습니다.</div>';
  document.getElementById('cartTotal').textContent = '예상 합계 ' + formatPrice(cart.reduce((sum, item) => sum + item.price * item.quantity, 0));
  target.querySelectorAll('[data-remove]').forEach(button => button.onclick = () => {
    saveCart(readCart().filter(item => item.id !== Number(button.dataset.remove))); renderCart();
  });
  target.querySelectorAll('[data-quantity]').forEach(input => input.onchange = () => {
    const value = Number(input.value);
    if (!Number.isInteger(value) || value < 1 || value > 999) {
      showMessage('cartMessage', '수량은 1~999개로 입력해주세요.', 'error'); renderCart(); return;
    }
    const rows = readCart();
    if (rows.find(item => item.id === Number(input.dataset.quantity))?.requestKey) { showMessage('cartMessage', '처리 결과 확인 전에는 수량을 바꿀 수 없습니다.', 'error'); renderCart(); return; }
    rows.find(item => item.id === Number(input.dataset.quantity)).quantity = value;
    saveCart(rows); renderCart();
  });
  const button = document.getElementById('checkoutBtn');
  button.disabled = !cart.length;
  button.onclick = async () => {
    if (!guardLogin()) return;
    // 처리 중 중복 클릭과 수량 변경을 막는다.
    button.disabled = true;
    target.querySelectorAll('input, button').forEach(el => el.disabled = true);
    let result;
    try { result = await checkoutCart(); }
    catch { showMessage('cartMessage', '처리 결과를 확인하지 못했습니다. 재주문 전 주문 서비스 로그를 확인해주세요.', 'error'); return; }
    renderCart();
    showMessage('cartMessage',
      result.succeeded + '개 상품 주문 완료.' + (result.failures.length ? ' 주문하지 못한 상품은 장바구니에 남겼습니다. ' + result.failures.join(' / ') : ''),
      result.failures.length ? 'error' : 'success');
  };
}

async function renderOrders() {
  const target = document.getElementById('orders');
  try {
    const rows = await apiRequest('/ordering-service/ordering/mine', { method: 'GET', cache: 'no-store' });
    const labels = { ORDERED:'주문 완료', FAILED:'실패·재고 해제 완료', PENDING:'재고 확인 중', CONFIRMING:'주문 확정 중', COMPENSATING:'재고 복구 중', CANCELED:'취소' };
    target.innerHTML = rows.length ? rows.map(o => `<article class="cart-row"><strong>주문 #${escapeHtml(o.id)}</strong><span>${escapeHtml(o.productName || '상품 #' + o.productId)}</span><span>${escapeHtml(o.quantity)}개</span><span>${escapeHtml(labels[o.status] || o.status)}</span></article>`).join('') : '<p>주문 내역이 없습니다.</p>';
  } catch (error) { target.textContent = error.message; }
}
