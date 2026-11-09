const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

function dashboard() {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, {textContent:'',className:'',style:{},addEventListener(){}});
    return elements.get(id);
  };
  const ctx = vm.createContext({document:{getElementById:get,hidden:false},renderHeader(){},
    setInterval(){},apiRequest:async()=>({}),showMessage(){},Date});
  vm.runInContext(fs.readFileSync(__dirname+'/../src/assets/admin.js','utf8'),ctx);
  return {ctx,get};
}

test('real counts and deployment status are displayed without HTML injection',()=>{
  const {ctx,get}=dashboard();
  ctx.applyDashboard({database:{status:'ok',members:3,products:5,orders:8,stock:27},
    monitoring:{grafana:'ok',metrics:'ok',nodesReady:4,podsReady:5},
    deployment:{status:'ok',sync:'Synced',health:'Healthy',revision:'abcdef123456'},checkedAt:new Date().toISOString()});
  assert.equal(get('ordersCount').textContent,'8');
  assert.equal(get('nodesReady').textContent,'4');
  assert.equal(get('appRevision').textContent,'abcdef1');
  assert.ok(get('overallStatus').className.endsWith('good'));
});

test('unavailable sources clear stale values instead of showing healthy or zero',()=>{
  const {ctx,get}=dashboard();
  ctx.applyDashboard({database:{status:'ok',orders:8},deployment:{status:'ok',sync:'Synced',health:'Healthy'}});
  ctx.applyDashboard({database:{status:'unavailable'},monitoring:{grafana:'unavailable'}});
  assert.equal(get('ordersCount').textContent,'—');
  assert.equal(get('nodesReady').textContent,'—');
  assert.equal(get('appRevision').textContent,'—');
  assert.ok(get('overallStatus').className.endsWith('warn'));
});
