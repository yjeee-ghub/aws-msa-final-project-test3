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
