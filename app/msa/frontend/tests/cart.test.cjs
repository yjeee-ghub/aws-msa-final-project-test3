const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function app(fetch) {
  const data = new Map();
  const context = vm.createContext({ console, fetch, FormData, URLSearchParams,
    window: { location: {} }, crypto: require("node:crypto").webcrypto, setTimeout, localStorage: { getItem: k => data.get(k), setItem: (k,v) => data.set(k,v), removeItem: k => data.delete(k) } });
  vm.runInContext(fs.readFileSync(__dirname + '/../src/assets/app.js', 'utf8'), context);
  context.saveAuth({id: 7, token: 'test'});
  return context;
}

test('quantity accumulation, stock cap and account isolation', () => {
  const c = app();
  c.addToCart({id: 1, name: 'test', price: 1500, stockQuantity: 5}, 2);
  c.addToCart({id: 1, name: 'test', price: 1500, stockQuantity: 5}, 3);
  assert.equal(c.readCart()[0].quantity, 5);
  assert.throws(() => c.addToCart({id: 1, stockQuantity: 5}, 1));
  c.saveAuth({id: 8, token: 'test'});
  assert.equal(c.readCart().length, 0);
});

test('checkout sends quantities and removes successes only', async () => {
  const requests = [];
  const c = app(async (url, options) => {
    const body = JSON.parse(options.body); requests.push(body);
    return { ok: body.productId === 1, status: body.productId === 1 ? 201 : 400,
      headers: { get: () => 'application/json' }, json: async () => ({id: 9, status: "ORDERED"}), text: async () => 'stock shortage' };
  });
  c.saveCart([{id:1,name:'a',quantity:3,price:100}, {id:2,name:'b',quantity:2,price:200}]);
  const result = await c.checkoutCart();
  assert.equal(result.succeeded, 1);
  assert.equal(result.failures.length, 1);
  assert.deepEqual(requests, [{productId:1,productCount:3}, {productId:2,productCount:2}]);
  assert.equal(c.readCart().length, 1);
  assert.equal(c.readCart()[0].id, 2);
});

test('corrupt browser state is handled and product text is escaped', () => {
  const c = app();
  c.localStorage.setItem('auth', 'invalid');
  assert.equal(c.getAuth(), null);
  c.localStorage.setItem(c.cartKey(), '{}');
  assert.equal(c.readCart().length, 0);
  assert.equal(c.escapeHtml('<img onerror="x">'), '&lt;img onerror=&quot;x&quot;&gt;');
});

test('network uncertainty retains the same checkout key for retry', async () => {
  const keys = [];
  let fail = true;
  const c = app(async (url, options) => {
    keys.push(options.headers['Idempotency-Key']);
    if (fail) throw new Error('response lost');
    return { ok:true, status:201, headers:{get:()=> 'application/json'}, json:async()=>({id:9,status:'ORDERED'}) };
  });
  c.saveCart([{id:1,name:'shoe',quantity:2,price:100}]);
  assert.equal((await c.checkoutCart()).succeeded, 0);
  assert.equal(c.readCart()[0].requestKey, keys[0]);
  fail = false;
  assert.equal((await c.checkoutCart()).succeeded, 1);
  assert.equal(keys[0], keys[1]);
});

test('202 processing is not displayed as an order success', async () => {
  const c = app(async () => ({ok:true,status:202,headers:{get:()=> 'application/json'},json:async()=>({id:9,status:'CONFIRMING'})}));
  c.setTimeout = callback => callback();
  c.saveCart([{id:1,name:'shoe',quantity:2,price:100}]);
  const result = await c.checkoutCart();
  assert.equal(result.succeeded, 0);
  assert.equal(result.failures.length, 1);
  assert.ok(c.readCart()[0].requestKey);
});
