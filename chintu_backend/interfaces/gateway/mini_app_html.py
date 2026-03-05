"""Telegram Mini App control-plane HTML renderer."""

from __future__ import annotations


def render_control_plane_mini_app_html() -> str:
    """Return a responsive control-plane dashboard for Telegram Mini App embedding."""
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Chintu Operator Console</title>
  <style>
    :root {
      --bg-a: #f3f9fb;
      --bg-b: #edf6f0;
      --surface: #ffffff;
      --surface-soft: #f7fbfe;
      --line: #d7e5ec;
      --text: #102028;
      --muted: #4f6775;
      --accent: #0b8f86;
      --accent-dark: #155c84;
      --ok: #21784a;
      --warn: #8d5e00;
      --danger: #9f2f2f;
      --chip: #e9f4f3;
      --radius: 14px;
      --shadow: 0 10px 24px rgba(16, 32, 40, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 12px;
      font-family: "Sora", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      color: var(--text);
      background: radial-gradient(1200px 600px at -10% -10%, #d5eeef 0%, transparent 55%),
                  radial-gradient(900px 500px at 110% 0%, #d9e8f8 0%, transparent 52%),
                  linear-gradient(170deg, var(--bg-a), var(--bg-b));
      min-height: 100vh;
      animation: fadein 180ms ease-out;
    }
    @keyframes fadein {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .wrap { max-width: 1180px; margin: 0 auto; }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }
    .title {
      margin: 0;
      font-size: 20px;
      font-weight: 700;
      color: var(--accent-dark);
      letter-spacing: .2px;
    }
    .top-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .auto { display: inline-flex; gap: 6px; align-items: center; color: var(--muted); font-size: 12px; }
    button, select, input {
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--text);
      border-radius: 9px;
      font-size: 13px;
      padding: 7px 9px;
      outline: none;
    }
    button {
      cursor: pointer;
      box-shadow: 0 2px 7px rgba(16, 32, 40, 0.06);
    }
    button.primary {
      border-color: #0b867e;
      background: linear-gradient(155deg, var(--accent), #0a7f77);
      color: #fff;
    }
    button.ghost {
      background: #fff;
      color: var(--muted);
    }
    button.warn {
      background: #fff4e2;
      border-color: #edd2a5;
      color: #8b5d00;
    }
    button.danger {
      background: #fff2f2;
      border-color: #efc9c9;
      color: var(--danger);
    }
    .error-box {
      display: none;
      margin-bottom: 10px;
      border: 1px solid #f0c8c8;
      background: #fff2f2;
      color: #8a3434;
      padding: 10px;
      border-radius: 10px;
      font-size: 12px;
    }
    .grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 10px; }
    .grid-2 { display: grid; grid-template-columns: 2fr 1fr; gap: 10px; margin-bottom: 10px; }
    .card {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: linear-gradient(180deg, var(--surface), var(--surface-soft));
      box-shadow: var(--shadow);
      padding: 12px;
    }
    .kpi-title { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .4px; margin-bottom: 6px; }
    .kpi-value { color: var(--accent-dark); font-size: 21px; font-weight: 700; }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }
    .section-title { margin: 0; font-size: 14px; color: var(--accent-dark); letter-spacing: .2px; }
    .muted { color: var(--muted); font-size: 12px; }
    .control-row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
    .approval-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
    .approval-item, .run-item, .artifact-item {
      border: 1px solid #dbe8ee;
      border-radius: 10px;
      padding: 9px;
      background: #fbfdff;
    }
    .item-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 6px;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      border: 1px solid #cae3e3;
      padding: 3px 9px;
      font-size: 11px;
      background: var(--chip);
      color: #0b625d;
      font-weight: 600;
    }
    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      display: inline-block;
      background: var(--muted);
    }
    .status-ok { background: var(--ok); }
    .status-warn { background: var(--warn); }
    .status-danger { background: var(--danger); }
    .approval-actions { margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }
    .run-grid { display: grid; gap: 8px; }
    .run-id { font-family: "Space Grotesk", "Consolas", monospace; font-size: 12px; font-weight: 600; color: #1d3b4a; }
    .run-status {
      border: 1px solid #cedee6;
      border-radius: 999px;
      padding: 3px 8px;
      text-transform: uppercase;
      font-size: 11px;
      font-weight: 600;
      color: #365768;
      background: #eff6fb;
    }
    .run-status.waiting_approval { color: #755000; background: #fff9e8; border-color: #ecd9a7; }
    .run-status.running { color: #11506c; background: #e6f5ff; border-color: #badff4; }
    .run-status.failed, .run-status.timed_out { color: var(--danger); background: #fff1f1; border-color: #efcbcb; }
    .run-status.completed { color: var(--ok); background: #ecf9f1; border-color: #c2e7cf; }
    .paging {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 8px;
      border-top: 1px dashed #dbe8ee;
      padding-top: 8px;
    }
    .telemetry-list { margin: 0; padding: 0; list-style: none; display: grid; gap: 7px; }
    .telemetry-row {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 12px;
      border-bottom: 1px dashed #dbe8ee;
      padding-bottom: 6px;
    }
    .telemetry-row:last-child { border-bottom: none; padding-bottom: 0; }
    .provider-trends { margin-top: 10px; display: grid; gap: 7px; }
    .provider-row {
      border: 1px solid #dce8ef;
      border-radius: 9px;
      padding: 8px;
      background: #fff;
      font-size: 12px;
    }
    .provider-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 4px;
    }
    .sparkline {
      font-family: "Consolas", "Courier New", monospace;
      letter-spacing: .6px;
      color: #2a657f;
      font-size: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .artifact-list { display: grid; gap: 7px; max-height: 520px; overflow: auto; padding-right: 4px; }
    a.link {
      color: #0a6881;
      text-decoration: none;
      word-break: break-all;
    }
    .footer {
      margin-top: 8px;
      color: var(--muted);
      font-size: 11px;
      display: flex;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
    }
    @media (max-width: 950px) {
      .grid-4 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .grid-2 { grid-template-columns: 1fr; }
      .approval-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 520px) {
      body { padding: 10px; }
      .title { font-size: 18px; }
      .kpi-value { font-size: 18px; }
      button, select, input { font-size: 12px; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <h1 class="title">Chintu Operator Console</h1>
      <div class="top-actions">
        <label class="auto">
          <input type="checkbox" id="auto-refresh" checked />
          Auto-refresh 10s
        </label>
        <button id="refresh" class="primary">Refresh</button>
      </div>
    </div>

    <div id="error-box" class="error-box"></div>

    <div class="grid-4">
      <div class="card"><div class="kpi-title">Queued</div><div class="kpi-value" id="kpi-queued">-</div></div>
      <div class="card"><div class="kpi-title">Running</div><div class="kpi-value" id="kpi-running">-</div></div>
      <div class="card"><div class="kpi-title">Waiting Approval</div><div class="kpi-value" id="kpi-waiting">-</div></div>
      <div class="card"><div class="kpi-title">Completed</div><div class="kpi-value" id="kpi-completed">-</div></div>
    </div>

    <div class="grid-2">
      <section class="card">
        <div class="section-head">
          <h2 class="section-title">Approvals Ledger</h2>
          <span class="muted" id="approval-count">0 pending</span>
        </div>
        <div id="approvals-grid" class="approval-grid"></div>
      </section>

      <section class="card">
        <div class="section-head">
          <h2 class="section-title">Telemetry</h2>
          <span class="muted" id="telemetry-note">live</span>
        </div>
        <ul class="telemetry-list" id="telemetry-list"></ul>
        <div class="provider-trends" id="provider-trends"></div>
      </section>
    </div>

    <div class="grid-2">
      <section class="card">
        <div class="section-head">
          <h2 class="section-title">Run Board</h2>
          <span class="muted" id="run-count">0 runs</span>
        </div>
        <div class="control-row">
          <select id="run-status-filter">
            <option value="all">All statuses</option>
            <option value="running">running</option>
            <option value="queued">queued</option>
            <option value="waiting_approval">waiting_approval</option>
            <option value="waiting_input">waiting_input</option>
            <option value="completed">completed</option>
            <option value="failed">failed</option>
            <option value="cancelled">cancelled</option>
            <option value="timed_out">timed_out</option>
          </select>
          <input id="run-search" type="text" placeholder="Search run id / summary"/>
          <select id="run-page-size">
            <option value="6">6 / page</option>
            <option value="8" selected>8 / page</option>
            <option value="12">12 / page</option>
          </select>
        </div>
        <div id="runs-grid" class="run-grid"></div>
        <div class="paging">
          <div>
            <button id="runs-prev" class="ghost">Prev</button>
            <button id="runs-next" class="ghost">Next</button>
          </div>
          <span class="muted" id="runs-page-info">page 1 / 1</span>
        </div>
      </section>

      <section class="card">
        <div class="section-head">
          <h2 class="section-title">Artifact Viewer</h2>
          <span class="muted">recent evidence</span>
        </div>
        <div class="control-row">
          <select id="artifact-kind-filter">
            <option value="all">All kinds</option>
            <option value="receipt">receipt</option>
            <option value="events">events</option>
            <option value="file">file</option>
            <option value="url">url</option>
            <option value="image">image</option>
            <option value="artifact">artifact</option>
          </select>
          <input id="artifact-search" type="text" placeholder="Search run / label / path"/>
          <select id="artifact-page-size">
            <option value="8">8 / page</option>
            <option value="12" selected>12 / page</option>
            <option value="20">20 / page</option>
          </select>
        </div>
        <div id="artifact-list" class="artifact-list"></div>
        <div class="paging">
          <div>
            <button id="artifact-prev" class="ghost">Prev</button>
            <button id="artifact-next" class="ghost">Next</button>
          </div>
          <span class="muted" id="artifact-page-info">page 1 / 1</span>
        </div>
      </section>
    </div>

    <div class="footer">
      <span id="last-updated">Last updated: -</span>
      <span id="owner-line">Owner-scoped session</span>
    </div>
  </div>

  <script>
    const qs = new URLSearchParams(window.location.search);
    const authToken = qs.get("token") || "";
    const uid = qs.get("uid") || "";
    const exp = qs.get("exp") || "";
    const sig = qs.get("sig") || "";

    const state = {
      latestCp: null,
      runsPage: 1,
      runsPageSize: 8,
      runsStatus: "all",
      runsSearch: "",
      artifactsPage: 1,
      artifactsPageSize: 12,
      artifactsKind: "all",
      artifactsSearch: "",
      limitRuns: 120,
      limitApprovals: 80,
    };

    function authHeaders() {
      const h = {};
      if (authToken) h["x-gateway-token"] = authToken;
      if (uid) h["x-telegram-user-id"] = uid;
      if (exp) h["x-ops-owner-exp"] = exp;
      if (sig) h["x-ops-owner-signature"] = sig;
      return h;
    }

    function esc(v) {
      return String(v || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function fmtTime(v) {
      if (!v) return "-";
      const d = new Date(v);
      if (Number.isNaN(d.getTime())) return String(v);
      return d.toLocaleString();
    }

    function showError(message) {
      const el = document.getElementById("error-box");
      if (!message) {
        el.style.display = "none";
        el.textContent = "";
        return;
      }
      el.style.display = "block";
      el.textContent = message;
    }

    function statusChip(ok) {
      const dotCls = ok ? "status-ok" : "status-danger";
      const label = ok ? "healthy" : "degraded";
      return `<span class="chip"><span class="status-dot ${dotCls}"></span>${label}</span>`;
    }

    function paginate(items, page, pageSize) {
      const total = items.length;
      const pages = Math.max(1, Math.ceil(total / pageSize));
      const safePage = Math.min(Math.max(1, page), pages);
      const start = (safePage - 1) * pageSize;
      return {
        page: safePage,
        pages,
        total,
        slice: items.slice(start, start + pageSize),
      };
    }

    function sparkline(values) {
      if (!Array.isArray(values) || !values.length) return "n/a";
      const chars = " .:-=+*#%@";
      return values.map((n) => {
        const x = Number(n);
        const clamped = Number.isFinite(x) ? Math.max(0, Math.min(1, x)) : 0;
        const idx = Math.min(chars.length - 1, Math.max(0, Math.round(clamped * (chars.length - 1))));
        return chars[idx];
      }).join("");
    }

    async function fetchControlPlane() {
      const requestQs = new URLSearchParams(qs.toString());
      requestQs.set("limit_runs", String(state.limitRuns));
      requestQs.set("limit_approvals", String(state.limitApprovals));
      const r = await fetch("/ops/control-plane?" + requestQs.toString(), { headers: authHeaders() });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || "control-plane request failed");
      return j.control_plane || {};
    }

    async function resolveApproval(approval, decision) {
      const payload = {
        kind: approval.kind || "action",
        decision,
        step_id: approval.step_id || "",
        approval_payload: approval.approval_payload || {},
        approval_signature: approval.approval_signature || "",
        user_id: uid || undefined,
      };
      const r = await fetch("/ops/resolve-approval?" + qs.toString(), {
        method: "POST",
        headers: { ...authHeaders(), "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || "approval resolution failed");
      return j.result || {};
    }

    function renderKpis(cp) {
      const counts = (((cp.run_board || {}).counts) || {});
      document.getElementById("kpi-queued").textContent = String(counts.queued || 0);
      document.getElementById("kpi-running").textContent = String(counts.running || 0);
      document.getElementById("kpi-waiting").textContent = String(counts.waiting_approval || 0);
      document.getElementById("kpi-completed").textContent = String(counts.completed || 0);
    }

    function renderApprovals(cp) {
      const approvals = (((cp.approvals_ledger || {}).pending) || []);
      const container = document.getElementById("approvals-grid");
      container.innerHTML = "";
      document.getElementById("approval-count").textContent = `${approvals.length} pending`;
      if (!approvals.length) {
        container.innerHTML = `<div class="approval-item muted">No pending approvals.</div>`;
        return;
      }
      approvals.forEach((approval, index) => {
        const title = approval.kind === "orchestrator_step"
          ? `Step ${esc(approval.step_id || approval.id || index + 1)}`
          : `Action ${esc(approval.capability || approval.id || index + 1)}`;
        const detail = esc(approval.message || approval.reason || "");
        const opts = Array.isArray(approval.decision_options) && approval.decision_options.length
          ? approval.decision_options
          : ["allow_once", "deny"];
        const row = document.createElement("div");
        row.className = "approval-item";
        row.innerHTML = `
          <div class="item-top">
            <strong>${title}</strong>
            <span class="run-status waiting_approval">${esc(approval.kind || "approval")}</span>
          </div>
          <div class="muted">${detail || "Awaiting operator decision."}</div>
          <div class="approval-actions"></div>
        `;
        const actionWrap = row.querySelector(".approval-actions");
        opts.forEach((decision) => {
          const btn = document.createElement("button");
          btn.className = decision === "deny" ? "danger" : (decision === "whitelist" ? "warn" : "ghost");
          btn.textContent = decision;
          btn.onclick = async () => {
            btn.disabled = true;
            try {
              await resolveApproval(approval, decision);
              await load();
            } catch (err) {
              showError(String(err.message || err));
              btn.disabled = false;
            }
          };
          actionWrap.appendChild(btn);
        });
        container.appendChild(row);
      });
    }

    function renderTelemetry(cp) {
      const telemetry = cp.telemetry || {};
      const resource = telemetry.resource || {};
      const providers = telemetry.provider_health || {};
      const trends = (telemetry.provider_trends || {}).providers || {};
      const providerNames = Object.keys(providers);
      const healthy = providerNames.filter((k) => {
        const item = providers[k] || {};
        return !!(item.available ?? item.ok ?? false);
      });

      const gpu = telemetry.gpu_inventory || {};
      const gpuDevices = Array.isArray(gpu.devices) ? gpu.devices : [];
      const gpuLine = gpuDevices.length
        ? gpuDevices.map((d) => `${d.name || d.id || "gpu"} ${d.memory_percent || d.utilization || "?"}%`).join(", ")
        : "n/a";

      const list = document.getElementById("telemetry-list");
      const providerOk = healthy.length === providerNames.length && providerNames.length > 0;
      list.innerHTML = `
        <li class="telemetry-row"><span>Provider health</span><span>${healthy.length}/${providerNames.length || 0} ${statusChip(providerOk)}</span></li>
        <li class="telemetry-row"><span>CPU / RAM</span><span>${Number(resource.cpu_percent || 0).toFixed(1)}% / ${Number(resource.ram_percent || 0).toFixed(1)}%</span></li>
        <li class="telemetry-row"><span>GPU inventory</span><span>${esc(gpuLine)}</span></li>
        <li class="telemetry-row"><span>VRAM pressure</span><span>${resource.gpu_pressure ? "high" : "normal"}</span></li>
        <li class="telemetry-row"><span>Recommendation</span><span>${esc(resource.recommendation || "none")}</span></li>
      `;
      document.getElementById("telemetry-note").textContent = `providers ${healthy.length}/${providerNames.length || 0}`;

      const trendEl = document.getElementById("provider-trends");
      trendEl.innerHTML = "";
      const names = Object.keys(trends).sort();
      if (!names.length) {
        trendEl.innerHTML = `<div class="provider-row muted">No provider trend data yet.</div>`;
        return;
      }
      names.forEach((name) => {
        const row = trends[name] || {};
        const totals = row.totals || {};
        const series = Array.isArray(row.success_rate_series) ? row.success_rate_series : [];
        const attempts = totals.attempts || 0;
        const successRate = Math.round((Number(totals.success_rate || 0) * 1000)) / 10;
        const available = !!row.latest_available;
        const reason = row.latest_reason || (available ? "ok" : "unknown");
        const block = document.createElement("div");
        block.className = "provider-row";
        block.innerHTML = `
          <div class="provider-head">
            <strong>${esc(name)}</strong>
            <span class="chip"><span class="status-dot ${available ? "status-ok" : "status-danger"}"></span>${available ? "available" : "unavailable"} (${esc(reason)})</span>
          </div>
          <div class="muted">attempts ${attempts} | success ${successRate}%</div>
          <div class="sparkline">${esc(sparkline(series))}</div>
        `;
        trendEl.appendChild(block);
      });
    }

    function filterRuns(cp) {
      const runs = Array.isArray(((cp.run_board || {}).runs)) ? cp.run_board.runs : [];
      const needle = state.runsSearch.trim().toLowerCase();
      return runs.filter((run) => {
        const status = String(run.status || "").toLowerCase();
        if (state.runsStatus !== "all" && status !== state.runsStatus) return false;
        if (!needle) return true;
        const hay = `${run.run_id || ""} ${run.result_summary || ""} ${run.outcome_label || ""}`.toLowerCase();
        return hay.includes(needle);
      });
    }

    function renderRuns(cp) {
      const filtered = filterRuns(cp);
      const result = paginate(filtered, state.runsPage, state.runsPageSize);
      state.runsPage = result.page;
      document.getElementById("run-count").textContent = `${result.total} runs`;
      document.getElementById("runs-page-info").textContent = `page ${result.page} / ${result.pages}`;
      const el = document.getElementById("runs-grid");
      el.innerHTML = "";
      if (!result.slice.length) {
        el.innerHTML = `<div class="run-item muted">No runs match current filter.</div>`;
        return;
      }
      result.slice.forEach((run) => {
        const links = Array.isArray(run.artifact_links) ? run.artifact_links.slice(0, 3) : [];
        const linkHtml = links.map((a) => {
          const raw = String(a.value || "");
          const href = raw.startsWith("http://") || raw.startsWith("https://")
            ? raw
            : `file:///${raw.replaceAll("\\\\", "/")}`;
          return `<a class="link" target="_blank" rel="noreferrer" href="${esc(href)}">${esc(a.label || a.kind || "artifact")}</a>`;
        }).join(" | ");
        const row = document.createElement("div");
        row.className = "run-item";
        row.innerHTML = `
          <div class="item-top">
            <span class="run-id">${esc(run.run_id || "run")}</span>
            <span class="run-status ${esc(run.status || "unknown")}">${esc(run.status || "unknown")}</span>
          </div>
          <div class="muted">${esc(run.result_summary || run.outcome_label || "")}</div>
          <div class="muted">started: ${esc(fmtTime(run.started_at || run.created_at))}</div>
          <div class="muted">artifacts: ${linkHtml || "none"}</div>
        `;
        el.appendChild(row);
      });
    }

    function filterArtifacts(cp) {
      const items = Array.isArray((((cp.artifact_viewer || {}).recent))) ? cp.artifact_viewer.recent : [];
      const needle = state.artifactsSearch.trim().toLowerCase();
      return items.filter((item) => {
        const kind = String(item.kind || "").toLowerCase();
        if (state.artifactsKind !== "all" && kind !== state.artifactsKind) return false;
        if (!needle) return true;
        const hay = `${item.run_id || ""} ${item.label || ""} ${item.value || ""}`.toLowerCase();
        return hay.includes(needle);
      });
    }

    function renderArtifacts(cp) {
      const filtered = filterArtifacts(cp);
      const result = paginate(filtered, state.artifactsPage, state.artifactsPageSize);
      state.artifactsPage = result.page;
      document.getElementById("artifact-page-info").textContent = `page ${result.page} / ${result.pages}`;
      const el = document.getElementById("artifact-list");
      el.innerHTML = "";
      if (!result.slice.length) {
        el.innerHTML = `<div class="artifact-item muted">No artifacts match current filter.</div>`;
        return;
      }
      result.slice.forEach((item) => {
        const raw = String(item.value || "");
        const href = raw.startsWith("http://") || raw.startsWith("https://")
          ? raw
          : `file:///${raw.replaceAll("\\\\", "/")}`;
        const row = document.createElement("div");
        row.className = "artifact-item";
        row.innerHTML = `
          <div class="item-top">
            <strong>${esc(item.run_id || "run")}</strong>
            <span class="chip">${esc(item.kind || "artifact")}</span>
          </div>
          <div><a class="link" target="_blank" rel="noreferrer" href="${esc(href)}">${esc(item.label || item.value || "artifact")}</a></div>
        `;
        el.appendChild(row);
      });
    }

    function wireControls() {
      document.getElementById("run-status-filter").addEventListener("change", (e) => {
        state.runsStatus = String(e.target.value || "all");
        state.runsPage = 1;
        renderRuns(state.latestCp || {});
      });
      document.getElementById("run-search").addEventListener("input", (e) => {
        state.runsSearch = String(e.target.value || "");
        state.runsPage = 1;
        renderRuns(state.latestCp || {});
      });
      document.getElementById("run-page-size").addEventListener("change", (e) => {
        state.runsPageSize = Math.max(1, Number(e.target.value || 8));
        state.runsPage = 1;
        renderRuns(state.latestCp || {});
      });
      document.getElementById("runs-prev").addEventListener("click", () => {
        state.runsPage = Math.max(1, state.runsPage - 1);
        renderRuns(state.latestCp || {});
      });
      document.getElementById("runs-next").addEventListener("click", () => {
        state.runsPage += 1;
        renderRuns(state.latestCp || {});
      });

      document.getElementById("artifact-kind-filter").addEventListener("change", (e) => {
        state.artifactsKind = String(e.target.value || "all");
        state.artifactsPage = 1;
        renderArtifacts(state.latestCp || {});
      });
      document.getElementById("artifact-search").addEventListener("input", (e) => {
        state.artifactsSearch = String(e.target.value || "");
        state.artifactsPage = 1;
        renderArtifacts(state.latestCp || {});
      });
      document.getElementById("artifact-page-size").addEventListener("change", (e) => {
        state.artifactsPageSize = Math.max(1, Number(e.target.value || 12));
        state.artifactsPage = 1;
        renderArtifacts(state.latestCp || {});
      });
      document.getElementById("artifact-prev").addEventListener("click", () => {
        state.artifactsPage = Math.max(1, state.artifactsPage - 1);
        renderArtifacts(state.latestCp || {});
      });
      document.getElementById("artifact-next").addEventListener("click", () => {
        state.artifactsPage += 1;
        renderArtifacts(state.latestCp || {});
      });
    }

    function renderAll(cp) {
      state.latestCp = cp || {};
      renderKpis(state.latestCp);
      renderApprovals(state.latestCp);
      renderTelemetry(state.latestCp);
      renderRuns(state.latestCp);
      renderArtifacts(state.latestCp);
      const ts = state.latestCp.generated_at_utc || new Date().toISOString();
      document.getElementById("last-updated").textContent = "Last updated: " + fmtTime(ts);
      document.getElementById("owner-line").textContent = uid ? `Owner uid ${uid} | signed session` : "Owner-scoped session";
    }

    async function load() {
      try {
        showError("");
        const cp = await fetchControlPlane();
        renderAll(cp);
      } catch (err) {
        showError(String(err.message || err));
      }
    }

    document.getElementById("refresh").addEventListener("click", load);
    wireControls();

    let timer = null;
    const auto = document.getElementById("auto-refresh");
    function syncTimer() {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
      if (auto.checked) {
        timer = setInterval(load, 10000);
      }
    }
    auto.addEventListener("change", syncTimer);
    syncTimer();
    load();
  </script>
</body>
</html>
    """.strip()
