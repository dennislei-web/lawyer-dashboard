/**
 * 視角切換 (View-As)
 *
 * 真實 admin 帳號可以暫時切換成「主管」或「律師」角色預覽 UI，
 * 不需登出登入。狀態存在 localStorage，跨 shell + iframe 子頁共享。
 *
 * 用法：
 *   1. 在子頁載入 currentLawyer 後：
 *        currentLawyer = window.ViewAs.apply(currentLawyer);
 *   2. 在 shell 注入下拉：
 *        window.ViewAs.installSelector(container, realRole, onChange);
 *   3. 登出時：
 *        window.ViewAs.clear();
 */
(function () {
  var KEY = 'lawyerDashViewAs';

  function getMode() {
    try { return localStorage.getItem(KEY) || 'real'; } catch (e) { return 'real'; }
  }

  function setMode(m) {
    try {
      if (!m || m === 'real') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, m);
    } catch (e) {}
  }

  function clear() {
    try { localStorage.removeItem(KEY); } catch (e) {}
  }

  // 對 admin lawyer 物件套用 override；非 admin 不動
  function apply(lawyer) {
    if (!lawyer || lawyer.role !== 'admin') return lawyer;
    var m = getMode();
    if (m === 'manager_upload')    return Object.assign({}, lawyer, { role: 'manager', can_upload: true });
    if (m === 'manager_no_upload') return Object.assign({}, lawyer, { role: 'manager', can_upload: false });
    if (m === 'lawyer')            return Object.assign({}, lawyer, { role: 'lawyer',  can_upload: false });
    return lawyer;
  }

  // 注入下拉到 container；只 realRole === 'admin' 才顯示
  function installSelector(container, realRole, onChange) {
    if (!container) return null;
    if (realRole !== 'admin') return null;
    if (container.querySelector('.view-as-select')) return null;
    var sel = document.createElement('select');
    sel.className = 'view-as-select';
    sel.title = '視角預覽（不影響真實權限）';
    sel.style.cssText = 'background:var(--ghost-bg,#1f1f24);color:var(--text,#e4e4e7);border:1px solid var(--border,#3f3f46);border-radius:8px;padding:5px 8px;font-size:0.8rem;cursor:pointer;outline:none;';
    sel.innerHTML = [
      '<option value="real">🔑 真實視角</option>',
      '<option value="manager_upload">📊 主管(可上傳)</option>',
      '<option value="manager_no_upload">📊 主管(不可上傳)</option>',
      '<option value="lawyer">🔒 律師</option>'
    ].join('');
    sel.value = getMode();
    sel.addEventListener('change', function () {
      setMode(sel.value);
      if (typeof onChange === 'function') onChange(sel.value);
    });
    container.insertBefore(sel, container.firstChild);
    return sel;
  }

  window.ViewAs = {
    getMode: getMode,
    setMode: setMode,
    clear: clear,
    apply: apply,
    installSelector: installSelector,
  };
})();
