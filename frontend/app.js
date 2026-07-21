/* ============================================================
   KYC Verifier — line-item dashboard
   ============================================================ */
const API = "/api";

const state = {
  rules: [],
  entities: [],          // each: {...entity, documents:[], run:{}|null}
  filter: "",
  expanded: new Set(),   // entity ids whose detail row is open
  running: new Set(),    // entity ids currently being verified
  newEntityType: "Individual",
  runningAll: false,
};

/* ------------------------- helpers ------------------------- */
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

function icons() { if (window.lucide) window.lucide.createIcons(); }

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function initials(name) {
  const p = String(name).trim().split(/\s+/);
  return ((p[0]?.[0] || "") + (p[1]?.[0] || p[0]?.[1] || "")).toUpperCase();
}

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { month: "short",
    day: "numeric", hour: "2-digit", minute: "2-digit" });
}

async function api(path, opts = {}) {
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

const nameOf = id => state.entities.find(e => e.id === id)?.name || "";

/* ------------------------- toasts -------------------------- */
function toast(kind, title, msg = "") {
  const t = document.createElement("div");
  t.className = "toast " + kind;
  const ic = kind === "ok" ? "check-circle-2" : kind === "err" ? "alert-circle" : "info";
  t.innerHTML = `<i data-lucide="${ic}"></i><div class="toast-body">
    <strong>${esc(title)}</strong>${msg ? `<span>${esc(msg)}</span>` : ""}</div>`;
  $("#toast-stack").appendChild(t);
  icons();
  setTimeout(() => {
    t.classList.add("out");
    setTimeout(() => t.remove(), 220);
  }, 3800);
}

/* ------------------------- modals -------------------------- */
function openModal(id) { $("#" + id).classList.add("show"); }
function closeModal(id) { $("#" + id).classList.remove("show"); }

$$(".modal-overlay").forEach(ov => {
  ov.addEventListener("mousedown", e => { if (e.target === ov) ov.classList.remove("show"); });
  $$("[data-close]", ov).forEach(b => b.addEventListener("click", () => ov.classList.remove("show")));
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") $$(".modal-overlay.show").forEach(m => m.classList.remove("show"));
});

let confirmCb = null;
function confirmDialog(title, text, okLabel, cb) {
  $("#confirm-title").textContent = title;
  $("#confirm-text").textContent = text;
  $("#confirm-ok").textContent = okLabel;
  confirmCb = cb;
  openModal("modal-confirm");
}
$("#confirm-ok").addEventListener("click", () => {
  closeModal("modal-confirm");
  if (confirmCb) confirmCb();
});

/* ===================== INITIALISE ========================= */
async function init() {
  bindGlobal();
  bindAuth();
  try {
    await api("/me");          // 200 → already signed in
    await showApp();
  } catch {
    showLogin();
  }
}

function showLogin() {
  $("#login-view").style.display = "flex";
  $("#app-view").style.display = "none";
  $("#login-password").value = "";
  $("#login-error").textContent = "";
  icons();
}

async function showApp() {
  $("#login-view").style.display = "none";
  $("#app-view").style.display = "";
  try {
    const health = await api("/health");
    if (!health.openai_configured)
      toast("err", "OpenAI key missing", "Set OPENAI_API_KEY in .env");
  } catch {}
  try { state.rules = await api("/rules"); } catch {}
  await loadDashboard();
  icons();
}

function bindAuth() {
  $("#login-form").addEventListener("submit", async e => {
    e.preventDefault();
    const btn = $("#login-btn"), err = $("#login-error");
    err.textContent = "";
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> Signing in…`;
    const fd = new FormData();
    fd.append("username", $("#login-username").value.trim());
    fd.append("password", $("#login-password").value);
    try {
      await api("/login", { method: "POST", body: fd });
      await showApp();
    } catch (ex) {
      err.textContent = ex.message || "Login failed";
    } finally {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="lock"></i> Sign In`;
      icons();
    }
  });
  $("#btn-logout").addEventListener("click", async () => {
    try { await api("/logout", { method: "POST" }); } catch {}
    state.entities = [];
    state.expanded.clear();
    showLogin();
  });
}

async function loadDashboard() {
  state.entities = await api("/dashboard");
  renderList();
}

/* ===================== RENDER ============================= */
function renderList() {
  $("#entity-count").textContent = state.entities.length;
  const list = $("#customer-list");
  const f = state.filter.toLowerCase();
  const items = state.entities.filter(e => e.name.toLowerCase().includes(f));

  const stats = state.entities.length ? statsHtml(state.entities) : "";

  if (!items.length) {
    list.innerHTML = stats + `<div class="page-empty">
      <i data-lucide="users"></i>
      <h2>${state.entities.length ? "No matching customers" : "No customers yet"}</h2>
      <p>${state.entities.length ? "Try a different search."
        : "Click “New Customer” to add one."}</p>
    </div>`;
    icons();
    return;
  }
  list.innerHTML = stats + `<div class="cust-table">
    <div class="ct-head">
      <div>Customer</div><div>Documents</div><div>Status</div><div>Verification</div>
    </div>
    ${items.map(rowHtml).join("")}
  </div>`;
  bindList();
  updateExportAll();
  icons();
}

function statsHtml(entities) {
  let verified = 0, flagged = 0, pending = 0;
  for (const e of entities) {
    const r = e.run;
    if (r && r.status === "completed") {
      if (r.overall === "FLAGGED") flagged++;
      else verified++;
    } else {
      pending++;
    }
  }
  const card = (icon, num, label, cls) => `
    <div class="stat-card ${cls}">
      <div class="sc-ic"><i data-lucide="${icon}"></i></div>
      <div class="sc-body">
        <div class="sc-num">${num}</div>
        <div class="sc-lbl">${label}</div>
      </div>
    </div>`;
  return `<div class="stats-row">
    ${card("users", entities.length, "Total Customers", "sc-total")}
    ${card("shield-check", verified, "Verified", "sc-verified")}
    ${card("shield-alert", flagged, "Flagged", "sc-flagged")}
    ${card("clock", pending, "Pending", "sc-pending")}
  </div>`;
}

function statusPill(run) {
  if (!run) return `<span class="status-pill sp-none"><span class="dotc"></span>Not run</span>`;
  if (run.status === "failed")
    return `<span class="status-pill sp-err"><span class="dotc"></span>Error</span>`;
  if (run.overall === "FLAGGED")
    return `<span class="status-pill sp-flag"><span class="dotc"></span>${run.fail_count} flag${run.fail_count===1?"":"s"}</span>`;
  return `<span class="status-pill sp-clear"><span class="dotc"></span>Clear</span>`;
}

function rowHtml(e) {
  const corp = e.entity_type === "Corporate";
  const running = state.running.has(e.id);
  const open = state.expanded.has(e.id);
  return `<div class="ct-row ${open ? "open" : ""}" data-id="${e.id}">
    <div class="ctr-main" data-toggle="${e.id}">
      <div class="ctr-name">
        <i class="ctr-chev" data-lucide="chevron-right"></i>
        <div class="ctr-nm">${esc(e.name)}</div>
      </div>
      <div class="ctr-docs">
        <i data-lucide="files"></i>${e.doc_count} document${e.doc_count===1?"":"s"}
      </div>
      <div class="ctr-status">
        ${running
          ? `<span class="status-pill sp-run"><span class="dotc"></span>Running…</span>`
          : statusPill(e.run)}
      </div>
      <div class="ctr-action">
        <button class="btn btn-primary btn-sm cc-run" data-run="${e.id}"
          ${(e.doc_count && !running) ? "" : "disabled"}>
          ${running ? `<span class="spinner"></span>` : `<i data-lucide="play"></i>`}
          Run Verification</button>
      </div>
    </div>
    ${open ? `<div class="ctr-detail">${detailHtml(e, running)}</div>` : ""}
  </div>`;
}

function detailHtml(e, running) {
  const docs = e.documents.length
    ? `<div class="doc-chips">${e.documents.map(docChipHtml).join("")}</div>`
    : `<span class="cc-muted">No documents uploaded.</span>`;
  return `
    <div class="detail-section">
      <div class="cc-label">Uploaded Documents (${e.documents.length})</div>
      ${docs}
    </div>
    <div class="detail-section">
      <div class="cc-label">Verification</div>
      ${verifyBlock(e, running)}
    </div>
    <div class="detail-foot">
      ${e.run && e.run.status === "completed" ? `
        <button class="btn btn-primary btn-sm" data-report="${e.id}">
          <i data-lucide="file-down"></i> Download Report</button>` : ""}
      <button class="btn btn-ghost btn-sm" data-del="${e.id}">
        <i data-lucide="trash-2"></i> Delete customer</button>
    </div>`;
}

function docChipHtml(d) {
  const isForm = d.doc_type === "application_form";
  return `<span class="doc-chip ${isForm ? "form" : "id"}">
    <i class="dc-ic" data-lucide="${isForm ? "file-text" : "id-card"}"></i>
    <span class="dc-name" title="${esc(d.original_name)}">${esc(d.original_name)}</span>
    <button class="dc-btn" data-view="${d.id}" data-ct="${esc(d.content_type)}"
      data-nm="${esc(d.original_name)}" title="View document">
      <i data-lucide="eye"></i></button>
  </span>`;
}

function verifyBlock(e, running) {
  if (running) {
    return `<div class="run-strip"><span class="spinner"></span>
      Analysing documents with AI vision — applying the ${state.rules.length} KYC checks…</div>`;
  }
  const run = e.run;
  if (!run) {
    return `<div class="cc-novf"><i data-lucide="circle-dashed"></i>
      Not verified yet — click “Run Verification”.</div>`;
  }
  if (run.status === "failed") {
    return `<div class="vbanner vb-err">
      <i class="vb-ic" data-lucide="alert-triangle"></i>
      <div class="vb-txt"><strong>Verification could not complete</strong>
        <span>${esc(run.error || "Unknown error")}</span></div></div>`;
  }
  const flagged = run.overall === "FLAGGED";
  const banner = `<div class="vbanner ${flagged ? "vb-flag" : "vb-clear"}">
    <i class="vb-ic" data-lucide="${flagged ? "shield-alert" : "shield-check"}"></i>
    <div class="vb-txt">
      <strong>${flagged
        ? `Flagged — ${run.fail_count} issue${run.fail_count===1?"":"s"} found`
        : "Clear — all checks passed"}</strong>
      <span>${run.pass_count} passed &middot; ${run.fail_count} flagged &middot; ${run.na_count} n/a &middot; ${fmtDate(run.created_at)}</span>
    </div></div>`;
  const results = `<div class="result-list">${(run.results || []).map(resultCard).join("")}</div>`;
  return banner + extractedPanel(run.extracted) + results;
}

function extractedPanel(ex) {
  if (!ex || !Object.keys(ex).length) return "";
  const ids = (ex.names_on_identity_documents || []).filter(Boolean);
  const exp = (ex.expiry_dates || []).filter(Boolean);
  const rows = [
    ["Name on form", ex.name_on_form],
    ["Name on ID(s)", ids.length ? ids.join(" · ") : null],
    ["Date of birth", ex.dob_on_form],
    ["ID expiry date(s)", exp.length ? exp.join(" · ") : null],
  ].filter(([, v]) => v);
  if (!rows.length) return "";
  return `<div class="extract-card">
    <div class="section-title"><i data-lucide="scan-line"></i> What the AI read</div>
    <div class="extract-grid">
      ${rows.map(([k, v]) => `<div class="extract-row">
        <span class="ek">${esc(k)}</span><span class="ev">${esc(v)}</span></div>`).join("")}
    </div>
  </div>`;
}

function resultCard(r) {
  const cls = r.status === "PASS" ? "r-pass" : r.status === "FAIL" ? "r-fail" : "r-na";
  const verdict = r.status === "PASS"
    ? `<span class="verdict v-pass"><i data-lucide="check-circle-2"></i>Pass</span>`
    : r.status === "FAIL"
    ? `<span class="verdict v-fail"><i data-lucide="x-circle"></i>Fail</span>`
    : `<span class="verdict v-na"><i data-lucide="minus-circle"></i>N/A</span>`;
  const docs = (r.documents_examined || []).map(d =>
    `<span class="chip"><i data-lucide="file"></i>${esc(d)}</span>`).join("");
  return `<div class="result ${cls}">
    <div class="result-top">
      <div class="result-id">
        <span class="rule-code">${esc(r.rule_id)}</span>
        <div><strong>${esc(r.flag_name)}</strong>
          <div class="step">${esc(r.process_step)}</div></div>
      </div>
      <div class="result-tags">
        ${verdict}
      </div>
    </div>
    <div class="result-evidence">
      ${r.status === "FAIL" ? `<div class="flag-line">
        <i data-lucide="flag"></i>${esc(r.flag)}</div>` : ""}
      ${esc(r.evidence)}
    </div>
    ${docs ? `<div class="result-docs">${docs}</div>` : ""}
  </div>`;
}

/* ===================== EVENT BINDING ====================== */
function bindList() {
  const list = $("#customer-list");
  $$(".ctr-main", list).forEach(m =>
    m.addEventListener("click", e => {
      if (e.target.closest(".cc-run")) return;
      const id = m.dataset.toggle;
      state.expanded.has(id) ? state.expanded.delete(id) : state.expanded.add(id);
      renderList();
    }));
  $$(".cc-run", list).forEach(b =>
    b.addEventListener("click", e => {
      e.stopPropagation();
      runVerifyCard(b.dataset.run);
    }));
  $$("[data-view]", list).forEach(b =>
    b.addEventListener("click", () => previewDoc(b.dataset.view, b.dataset.nm, b.dataset.ct)));
  $$("[data-del]", list).forEach(b =>
    b.addEventListener("click", () => deleteEntity(b.dataset.del)));
  $$("[data-report]", list).forEach(b =>
    b.addEventListener("click", () => downloadFile(
      `${API}/entities/${b.dataset.report}/report.pdf`)));
}

function downloadFile(url) {
  const a = document.createElement("a");
  a.href = url;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  setTimeout(() => a.remove(), 200);
}

function updateExportAll() {
  const anyDone = state.entities.some(
    e => e.run && e.run.status === "completed");
  const btn = $("#btn-export-all");
  if (btn) btn.disabled = !anyDone;
}

/* ===================== VERIFICATION ======================= */
async function runVerifyCard(id) {
  if (state.running.has(id)) return;
  state.running.add(id);
  state.expanded.add(id);          // open the row so progress + result are visible
  renderList();
  try {
    const run = await api(`/entities/${id}/verify`, { method: "POST" });
    state.running.delete(id);
    await loadDashboard();
    if (run.status === "failed") toast("err", "Verification failed", run.error);
    else if (run.overall === "FLAGGED")
      toast("err", `Flagged — ${run.fail_count} issue(s)`, nameOf(id));
    else toast("ok", "Verification clear", nameOf(id));
  } catch (err) {
    state.running.delete(id);
    toast("err", "Verification failed", err.message);
    await loadDashboard();
  }
}

async function runAll() {
  if (state.runningAll) return;
  const targets = state.entities.filter(e => e.doc_count > 0);
  if (!targets.length) {
    toast("info", "Nothing to run", "No customers have documents uploaded.");
    return;
  }
  state.runningAll = true;
  const btn = $("#btn-run-all");
  btn.disabled = true;
  let done = 0, flagged = 0, errors = 0;
  for (const e of targets) {
    btn.innerHTML = `<span class="spinner"></span> Running ${done + 1}/${targets.length}…`;
    state.running.add(e.id);
    renderList();
    try {
      const run = await api(`/entities/${e.id}/verify`, { method: "POST" });
      if (run.status === "failed") errors++;
      else if (run.overall === "FLAGGED") flagged++;
    } catch { errors++; }
    state.running.delete(e.id);
    done++;
    await loadDashboard();
  }
  state.runningAll = false;
  btn.disabled = false;
  btn.innerHTML = `<i data-lucide="zap"></i> Run All Verifications`;
  icons();
  toast(errors ? "err" : flagged ? "info" : "ok",
    `Bulk run complete — ${done} customer(s)`,
    `${flagged} flagged · ${done - flagged - errors} clear · ${errors} error(s)`);
}

/* ===================== DOCUMENTS ========================== */
function previewDoc(id, name, ct) {
  $("#preview-title").textContent = name;
  const src = `${API}/documents/${id}/file`;
  $("#preview-body").innerHTML = (ct || "").startsWith("image/")
    ? `<img src="${src}" alt="${esc(name)}" />`
    : `<iframe src="${src}" title="${esc(name)}"></iframe>`;
  openModal("modal-preview");
}

/* ===================== ENTITY CRUD ======================== */
function deleteEntity(id) {
  const name = nameOf(id);
  confirmDialog("Delete customer",
    `“${name}” and all its documents & verification runs will be permanently deleted.`,
    "Delete", async () => {
      try {
        await api(`/entities/${id}`, { method: "DELETE" });
        toast("ok", "Customer deleted", name);
        state.expanded.delete(id);
        await loadDashboard();
      } catch (err) { toast("err", "Delete failed", err.message); }
    });
}

/* ===================== GLOBAL BINDINGS ==================== */
function bindGlobal() {
  $("#entity-search").addEventListener("input", e => {
    state.filter = e.target.value;
    renderList();
  });
  $("#btn-new-entity").addEventListener("click", () => openModal("modal-new-entity"));
  $("#btn-run-all").addEventListener("click", runAll);
  $("#btn-export-all").addEventListener("click", () =>
    downloadFile(`${API}/reports.zip`));

  $$("#new-entity-type .seg").forEach(s => s.addEventListener("click", () => {
    state.newEntityType = s.dataset.val;
    $$("#new-entity-type .seg").forEach(x => x.classList.toggle("active", x === s));
  }));

  $("#form-new-entity").addEventListener("submit", async e => {
    e.preventDefault();
    const name = $("#new-entity-name").value.trim();
    if (!name) return;
    const fd = new FormData();
    fd.append("name", name);
    fd.append("entity_type", state.newEntityType);
    try {
      await api("/entities", { method: "POST", body: fd });
      closeModal("modal-new-entity");
      $("#new-entity-name").value = "";
      toast("ok", "Customer created", name);
      await loadDashboard();
    } catch (err) { toast("err", "Could not create", err.message); }
  });
}

document.addEventListener("DOMContentLoaded", init);
