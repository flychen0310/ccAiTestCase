const API_BASE = "/api";

const CASE_TYPE_LABEL = { functional: "正向功能", boundary: "边界值/等价类", exception: "异常/容错" };
const REVIEW_STATUS_LABEL = { pending: "待审核", accepted: "已采纳", rejected: "已驳回", edited: "已编辑" };
const REQ_STATUS_LABEL = { draft: "草稿", analyzing: "理解中...", analyzed: "已理解", failed: "失败" };

const state = {
  requirements: [],
  selectedRequirement: null, // 详情(含 analysis)
  cases: [],
  filters: { case_type: "", review_status: "" },
  editingCase: null, // 正在编辑的用例(深拷贝)
};

// ---------------- API 封装 ----------------

async function api(path, options = {}) {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail || detail;
    } catch (_) {
      /* ignore */
    }
    throw new Error(detail);
  }
  const contentType = resp.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return resp.json();
  }
  return resp;
}

const Api = {
  listRequirements: () => api("/requirements"),
  createRequirement: (payload) => api("/requirements", { method: "POST", body: JSON.stringify(payload) }),
  getRequirement: (id) => api(`/requirements/${id}`),
  analyze: (id) => api(`/requirements/${id}/analyze`, { method: "POST" }),
  generate: (id, caseTypes) =>
    api(`/requirements/${id}/generate`, { method: "POST", body: JSON.stringify({ case_types: caseTypes }) }),
  listCases: (id, filters) => {
    const params = new URLSearchParams();
    if (filters.case_type) params.set("case_type", filters.case_type);
    if (filters.review_status) params.set("review_status", filters.review_status);
    const qs = params.toString();
    return api(`/requirements/${id}/cases${qs ? "?" + qs : ""}`);
  },
  updateCase: (id, payload) => api(`/cases/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteCase: (id) => api(`/cases/${id}`, { method: "DELETE" }),
};

// ---------------- 工具函数 ----------------

function toast(message, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.classList.remove("hidden");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => el.classList.add("hidden"), 3200);
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function formatTime(iso) {
  if (!iso) return "";
  return iso.replace("T", " ").slice(0, 16);
}

function openModal(id) {
  document.getElementById(id).classList.remove("hidden");
}

function closeModal(id) {
  document.getElementById(id).classList.add("hidden");
}

document.querySelectorAll("[data-close-modal]").forEach((btn) => {
  btn.addEventListener("click", () => closeModal(btn.dataset.closeModal));
});

// ---------------- 需求列表 ----------------

async function loadRequirements() {
  state.requirements = await Api.listRequirements();
  renderRequirementList();
}

function renderRequirementList() {
  const container = document.getElementById("requirement-list");
  if (state.requirements.length === 0) {
    container.innerHTML = `<div class="requirement-empty-hint">还没有需求,点击右上角"新建需求"开始</div>`;
    return;
  }
  container.innerHTML = state.requirements
    .map((req) => {
      const active = state.selectedRequirement && state.selectedRequirement.id === req.id;
      return `
        <div class="requirement-item ${active ? "active" : ""}" data-req-id="${req.id}">
          <div class="requirement-item-title">${escapeHtml(req.title)}</div>
          <div class="requirement-item-meta">
            <span>${REQ_STATUS_LABEL[req.status] || req.status}</span>
            <span>${formatTime(req.created_at)}</span>
          </div>
        </div>`;
    })
    .join("");
}

document.getElementById("requirement-list").addEventListener("click", (e) => {
  const item = e.target.closest(".requirement-item");
  if (item) selectRequirement(Number(item.dataset.reqId));
});

async function selectRequirement(id) {
  const detail = await Api.getRequirement(id);
  state.selectedRequirement = detail;
  document.getElementById("empty-state").classList.add("hidden");
  document.getElementById("requirement-detail").classList.remove("hidden");
  renderRequirementList();
  renderRequirementDetail();
  if (detail.analysis) {
    await refreshCases();
  } else {
    document.getElementById("cases-section").classList.add("hidden");
    document.getElementById("analysis-section").classList.add("hidden");
  }
}

function renderRequirementDetail() {
  const req = state.selectedRequirement;
  document.getElementById("req-title").textContent = req.title;
  document.getElementById("req-content").textContent = req.content;
  const statusEl = document.getElementById("req-status");
  statusEl.textContent = REQ_STATUS_LABEL[req.status] || req.status;
  document.getElementById("analyze-status").textContent = "";

  const analysisSection = document.getElementById("analysis-section");
  if (req.analysis) {
    analysisSection.classList.remove("hidden");
    renderAnalysis(req.analysis);
  } else {
    analysisSection.classList.add("hidden");
  }
}

function renderAnalysis(analysis) {
  const renderList = (elId, items) =>
    (document.getElementById(elId).innerHTML =
      items.length > 0 ? items.map((t) => `<li>${escapeHtml(t)}</li>`).join("") : `<li>(无)</li>`);
  renderList("list-feature-points", analysis.feature_points);
  renderList("list-business-rules", analysis.business_rules);
  renderList("list-edge-cases", analysis.edge_cases);
  renderList("list-open-questions", analysis.open_questions);
}

// ---------------- 新建需求 ----------------

document.getElementById("btn-new-requirement").addEventListener("click", () => {
  document.getElementById("input-req-title").value = "";
  document.getElementById("input-req-content").value = "";
  openModal("modal-new-requirement");
});

document.getElementById("btn-submit-requirement").addEventListener("click", async (e) => {
  const title = document.getElementById("input-req-title").value.trim();
  const content = document.getElementById("input-req-content").value.trim();
  if (!title || !content) {
    toast("请填写需求标题和描述", true);
    return;
  }
  e.target.disabled = true;
  try {
    const req = await Api.createRequirement({ title, content });
    closeModal("modal-new-requirement");
    await loadRequirements();
    await selectRequirement(req.id);
    toast("需求创建成功");
  } catch (err) {
    toast(`创建失败: ${err.message}`, true);
  } finally {
    e.target.disabled = false;
  }
});

// ---------------- AI 需求理解 ----------------

document.getElementById("btn-analyze").addEventListener("click", async (e) => {
  const req = state.selectedRequirement;
  e.target.disabled = true;
  document.getElementById("analyze-status").textContent = "AI 正在理解需求,请稍候(约 5~20 秒)...";
  try {
    await Api.analyze(req.id);
    const detail = await Api.getRequirement(req.id);
    state.selectedRequirement = detail;
    await loadRequirements();
    renderRequirementDetail();
    toast("需求理解完成");
  } catch (err) {
    toast(`需求理解失败: ${err.message}`, true);
    document.getElementById("analyze-status").textContent = "";
  } finally {
    e.target.disabled = false;
  }
});

// ---------------- 用例生成 ----------------

document.getElementById("btn-generate").addEventListener("click", async (e) => {
  const req = state.selectedRequirement;
  const caseTypes = Array.from(
    document.querySelectorAll("#analysis-section .checkbox input:checked")
  ).map((cb) => cb.value);

  if (caseTypes.length === 0) {
    toast("请至少选择一种用例类型", true);
    return;
  }

  e.target.disabled = true;
  document.getElementById("generate-status").textContent = `AI 正在生成用例,请稍候(约 ${
    caseTypes.length * 15
  } 秒)...`;
  document.getElementById("generate-summary").innerHTML = "";

  try {
    const result = await Api.generate(req.id, caseTypes);
    document.getElementById("generate-summary").innerHTML = result.stages
      .map((s) => {
        const ok = s.status === "success";
        return `<span>${CASE_TYPE_LABEL[s.case_type]}: ${
          ok ? `生成 ${s.generated_count} 条 (tokens ${s.input_tokens}/${s.output_tokens})` : `失败 - ${escapeHtml(s.error_message || "")}`
        }</span>`;
      })
      .join("");
    toast(`共生成 ${result.total_cases} 条用例`);
    document.getElementById("cases-section").classList.remove("hidden");
    await refreshCases();
  } catch (err) {
    toast(`生成失败: ${err.message}`, true);
  } finally {
    e.target.disabled = false;
    document.getElementById("generate-status").textContent = "";
  }
});

// ---------------- 用例列表 ----------------

async function refreshCases() {
  const req = state.selectedRequirement;
  document.getElementById("cases-section").classList.remove("hidden");
  state.cases = await Api.listCases(req.id, state.filters);
  renderCaseTable();
}

function renderCaseTable() {
  document.getElementById("case-count").textContent = state.cases.length;
  const tbody = document.getElementById("case-table-body");

  if (state.cases.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">暂无用例</td></tr>`;
    return;
  }

  tbody.innerHTML = state.cases
    .map(
      (c) => `
      <tr data-case-id="${c.id}">
        <td class="col-id">${c.id}</td>
        <td class="case-title-cell" data-action="edit">${escapeHtml(c.title)}</td>
        <td class="col-type"><span class="type-tag">${CASE_TYPE_LABEL[c.case_type] || c.case_type}</span></td>
        <td class="col-priority"><span class="priority-tag priority-${c.priority}">${c.priority}</span></td>
        <td class="col-status"><span class="status-tag status-${c.review_status}">${REVIEW_STATUS_LABEL[c.review_status] || c.review_status}</span></td>
        <td class="col-actions">
          <div class="row-actions">
            <button class="link-btn" data-action="accept">采纳</button>
            <button class="link-btn danger" data-action="reject">驳回</button>
          </div>
        </td>
      </tr>`
    )
    .join("");
}

document.getElementById("case-table-body").addEventListener("click", async (e) => {
  const row = e.target.closest("tr[data-case-id]");
  if (!row) return;
  const caseId = Number(row.dataset.caseId);
  const action = e.target.dataset.action;

  if (action === "edit") {
    openCaseEditor(state.cases.find((c) => c.id === caseId));
  } else if (action === "accept") {
    await quickUpdateCase(caseId, { review_status: "accepted" });
  } else if (action === "reject") {
    await quickUpdateCase(caseId, { review_status: "rejected" });
  }
});

async function quickUpdateCase(caseId, payload) {
  try {
    await Api.updateCase(caseId, payload);
    await refreshCases();
  } catch (err) {
    toast(`更新失败: ${err.message}`, true);
  }
}

document.getElementById("filter-case-type").addEventListener("change", (e) => {
  state.filters.case_type = e.target.value;
  refreshCases();
});

document.getElementById("filter-review-status").addEventListener("change", (e) => {
  state.filters.review_status = e.target.value;
  refreshCases();
});

// ---------------- 用例编辑弹窗 ----------------

function openCaseEditor(caseItem) {
  state.editingCase = JSON.parse(JSON.stringify(caseItem));
  document.getElementById("edit-case-title").value = state.editingCase.title;
  document.getElementById("edit-case-precondition").value = state.editingCase.precondition || "";
  document.getElementById("edit-case-priority").value = state.editingCase.priority;
  document.getElementById("edit-case-review-status").value = state.editingCase.review_status;
  document.getElementById("edit-case-comment").value = state.editingCase.review_comment || "";
  renderStepsEditor();
  openModal("modal-edit-case");
}

function renderStepsEditor() {
  const container = document.getElementById("edit-case-steps");
  container.innerHTML = state.editingCase.steps
    .map(
      (s, i) => `
      <div class="step-row" data-step-index="${i}">
        <div class="step-index">${i + 1}</div>
        <textarea class="textarea step-input" rows="2" placeholder="操作步骤">${escapeHtml(s.step)}</textarea>
        <textarea class="textarea expected-input" rows="2" placeholder="预期结果">${escapeHtml(s.expected)}</textarea>
        <button class="step-remove" data-action="remove-step" title="删除该步骤">&times;</button>
      </div>`
    )
    .join("");
}

document.getElementById("edit-case-steps").addEventListener("click", (e) => {
  if (e.target.dataset.action === "remove-step") {
    const idx = Number(e.target.closest(".step-row").dataset.stepIndex);
    state.editingCase.steps.splice(idx, 1);
    renderStepsEditor();
  }
});

document.getElementById("btn-add-step").addEventListener("click", () => {
  state.editingCase.steps.push({ step: "", expected: "" });
  renderStepsEditor();
});

function collectStepsFromEditor() {
  return Array.from(document.querySelectorAll("#edit-case-steps .step-row")).map((row) => ({
    step: row.querySelector(".step-input").value.trim(),
    expected: row.querySelector(".expected-input").value.trim(),
  }));
}

document.getElementById("btn-save-case").addEventListener("click", async (e) => {
  const payload = {
    title: document.getElementById("edit-case-title").value.trim(),
    precondition: document.getElementById("edit-case-precondition").value.trim(),
    steps: collectStepsFromEditor(),
    priority: document.getElementById("edit-case-priority").value,
    review_status: document.getElementById("edit-case-review-status").value,
    review_comment: document.getElementById("edit-case-comment").value.trim(),
  };
  if (!payload.title || payload.steps.length === 0) {
    toast("标题和至少一个步骤是必填的", true);
    return;
  }
  e.target.disabled = true;
  try {
    await Api.updateCase(state.editingCase.id, payload);
    closeModal("modal-edit-case");
    await refreshCases();
    toast("保存成功");
  } catch (err) {
    toast(`保存失败: ${err.message}`, true);
  } finally {
    e.target.disabled = false;
  }
});

document.getElementById("btn-delete-case").addEventListener("click", async () => {
  if (!confirm("确定删除这条用例吗?")) return;
  try {
    await Api.deleteCase(state.editingCase.id);
    closeModal("modal-edit-case");
    await refreshCases();
    toast("已删除");
  } catch (err) {
    toast(`删除失败: ${err.message}`, true);
  }
});

// ---------------- 导出 ----------------

async function exportCases(format) {
  const req = state.selectedRequirement;
  try {
    const resp = await fetch(`${API_BASE}/cases/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requirement_id: req.id, format }),
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new Error(body.detail || resp.statusText);
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `test_cases.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    toast(`导出失败: ${err.message}`, true);
  }
}

document.getElementById("btn-export-xlsx").addEventListener("click", () => exportCases("xlsx"));
document.getElementById("btn-export-csv").addEventListener("click", () => exportCases("csv"));

// ---------------- 初始化 ----------------

loadRequirements();
