const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// FRONTEND_SOURCE is used by the isolated demo rehearsal; CI uses the real source.
const source = process.env.FRONTEND_SOURCE || path.join(__dirname, '../src/assets/app.js');
function app() {
  const context = vm.createContext({ window: { location: {} }, URLSearchParams });
  vm.runInContext(fs.readFileSync(source, 'utf8'), context);
  return context;
}
test('product card link supplies the id read by the detail page', () => {
  const c = app();
  c.window.location.search = new URL(c.getProductDetailUrl(7), 'https://example.test').search;
  assert.equal(c.getQueryParam('id'), '7');
  c.goToProductDetail(7);
  assert.equal(c.window.location.href, '/product-detail.html?id=7');
});
test('product card renders a link that resolves to the requested product', async () => {
  const c = app();
  const list = { innerHTML: '' };
  c.document = { getElementById: name => name === 'productList' ? list : null };
  c.apiRequest = async () => [{ id: 7, name: 'Test product', stockQuantity: 2, price: 1000 }];
  await c.loadProducts();
  const href = list.innerHTML.match(/class="card card-link" href="([^"]+)"/)[1];
  c.window.location.search = new URL(href, 'https://example.test').search;
  assert.equal(c.getQueryParam('id'), '7');
});
