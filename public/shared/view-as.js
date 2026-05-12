/**
 * 視角切換 (View-As)
 *
 * 真實 admin 帳號可以暫時切換成「主管」「律師」或「特定律師身份」預覽 UI，
 * 不需登出登入。狀態存在 localStorage，跨 shell + iframe 子頁共享。
 *
 * Modes:
 *   - 'real'                  → 真實 admin 視角
 *   - 'manager_upload'        → 通用主管(可上傳)
 *   - 'manager_no_upload'     → 通用主管(不可上傳)
 *   - 'lawyer'                → 通用律師
 *   - 'as_lawyer'             → 以特定律師身份（lawyer 物件存在 KEY_LAWYER）
 *
 * 用法：
 *   1. 子頁載入 currentLawyer 後：
 *        currentLawyer = window.ViewAs.apply(currentLawyer);
 *   2. shell 注入下拉：
 *        window.ViewAs.installSelector(container, realLawyer, allLawyers, onChange);
 *   3. 登出時：
 *        window.ViewAs.clear();
 */
(function () {
  var KEY        = 'lawyerDashViewAs';
  var KEY_LAWYER = 'lawyerDashViewAsLawyer';

  function getMode() {
    try { return localStorage.getItem(KEY) || 'real'; } catch (e) { return 'real'; }
  }

  function getTargetLawyer() {
    try {
      var s = localStorage.getItem(KEY_LAWYER);
      return s ? JSON.parse(s) : null;
    } catch (e) { return null; }
  }

  function setMode(m, targetLawyer) {
    try {
      if (!m || m === 'real') {
        localStorage.removeItem(KEY);
        localStorage.removeItem(KEY_LAWYER);
      } else {
        localStorage.setItem(KEY, m);
        if (m === 'as_lawyer' && targetLawyer) {
          localStorage.setItem(KEY_LAWYER, JSON.stringify(targetLawyer));
        } else if (m !== 'as_lawyer') {
          localStorage.removeItem(KEY_LAWYER);
        }
      }
    } catch (e) {}
  }

  function clear() {
    try {
      localStorage.removeItem(KEY);
      localStorage.removeItem(KEY_LAWYER);
    } catch (e) {}
  }

  // 對 admin lawyer 物件套用 override；非 admin 不動
  function apply(lawyer) {
    if (!lawyer || lawyer.role !== 'admin') return lawyer;
    var m = getMode();
    if (m === 'manager_upload')    return Object.assign({}, lawyer, { role: 'manager', can_upload: true });
    if (m === 'manager_no_upload') return Object.assign({}, lawyer, { role: 'manager', can_upload: false });
    if (m === 'lawyer')            return Object.assign({}, lawyer, { role: 'lawyer',  can_upload: false });
    if (m === 'as_lawyer') {
      var target = getTargetLawyer();
      if (target) return Object.assign({}, target);
    }
    return lawyer;
  }

  // 注入下拉到 container；只 realLawyer.role === 'admin' 才顯示
  // allLawyers: 所有律師清單，用來組「指定身份」分組
  function installSelector(container, realLawyer, allLawyers, onChange) {
    if (!container) return null;
    if (!realLawyer || realLawyer.role !== 'admin') return null;
    if (container.querySelector('.view-as-select')) return null;

    var sel = document.createElement('select');
    sel.className = 'view-as-select';
    sel.title = '視角預覽（不影響真實權限）';
    sel.style.cssText = 'background:var(--ghost-bg,#1f1f24);color:var(--text,#e4e4e7);border:1px solid var(--border,#3f3f46);border-radius:8px;padding:5px 8px;font-size:0.8rem;cursor:pointer;outline:none;max-width:200px;';

    var html = [];
    html.push('<optgroup label="角色視角">');
    html.push('<option value="real">🔑 真實視角</option>');
    html.push('<option value="manager_upload">📊 主管 (可上傳)</option>');
    html.push('<option value="manager_no_upload">📊 主管 (不可上傳)</option>');
    html.push('<option value="lawyer">🔒 律師</option>');
    html.push('</optgroup>');

    // 部門主管身份
    var managers = (allLawyers || []).filter(function (l) {
      return l && l.role === 'manager' && l.is_active !== false && l.id !== realLawyer.id;
    });
    managers.sort(function (a, b) { return (a.name || '').localeCompare(b.name || ''); });
    if (managers.length) {
      html.push('<optgroup label="部門主管身份">');
      managers.forEach(function (l) {
        var canUploadLabel = l.can_upload ? '⬆' : '';
        html.push('<option value="as:' + l.id + '">📊 ' + escapeHtml(l.name || l.id) + (canUploadLabel ? ' ' + canUploadLabel : '') + '</option>');
      });
      html.push('</optgroup>');
    }

    // 律師身份
    var lawyersList = (allLawyers || []).filter(function (l) {
      return l && l.role === 'lawyer' && l.is_active !== false && l.id !== realLawyer.id;
    });
    lawyersList.sort(function (a, b) { return (a.name || '').localeCompare(b.name || ''); });
    if (lawyersList.length) {
      html.push('<optgroup label="律師身份">');
      lawyersList.forEach(function (l) {
        html.push('<option value="as:' + l.id + '">🔒 ' + escapeHtml(l.name || l.id) + '</option>');
      });
      html.push('</optgroup>');
    }

    sel.innerHTML = html.join('');

    // 設定目前選擇
    var currentMode = getMode();
    if (currentMode === 'as_lawyer') {
      var target = getTargetLawyer();
      if (target && target.id) {
        sel.value = 'as:' + target.id;
      } else {
        sel.value = 'real';
      }
    } else {
      sel.value = currentMode;
    }
    // 萬一某律師已被刪掉，找不到選項就退回 real
    if (sel.value === '' || sel.selectedIndex < 0) sel.value = 'real';

    sel.addEventListener('change', function () {
      var val = sel.value;
      if (val.indexOf('as:') === 0) {
        var lawyerId = val.substring(3);
        var target = (allLawyers || []).find(function (l) { return l && l.id === lawyerId; });
        if (target) setMode('as_lawyer', target);
      } else {
        setMode(val);
      }
      if (typeof onChange === 'function') onChange(val);
    });

    container.insertBefore(sel, container.firstChild);
    return sel;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  window.ViewAs = {
    getMode: getMode,
    getTargetLawyer: getTargetLawyer,
    setMode: setMode,
    clear: clear,
    apply: apply,
    installSelector: installSelector,
  };
})();
