const API_BASE = "/api";

const CASE_TYPE_LABEL = { functional: "正向功能", boundary: "边界值/等价类", exception: "异常/容错" };
const REVIEW_STATUS_LABEL = { pending: "待审核", accepted: "已采纳", rejected: "已驳回", edited: "已编辑" };
const REQ_STATUS_LABEL = { draft: "草稿", analyzing: "理解中...", analyzed: "已理解", failed: "失败" };
const SOURCE_LABEL = { ai: "AI 生成", manual: "人工新增" };

const state = {
  requirements: [],
  selectedRequirement: null, // 详情(含 analysis)
  cases: [],
  filters: { case_type: "", review_status: "" },
  editingCase: null, // 正在编辑/新增的用例(深拷贝);新增模式下 id 为 null
  caseEditorMode: "edit", // "edit" | "create"
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
  fetchLink: (url) => api("/requirements/fetch-link", { method: "POST", body: JSON.stringify({ url }) }),
  getRequirement: (id) => api(`/requirements/${id}`),
  deleteRequirement: (id) => api(`/requirements/${id}`, { method: "DELETE" }),
  analyze: (id) => api(`/requirements/${id}/analyze`, { method: "POST" }),
  updateAnalysis: (id, payload) => api(`/requirements/${id}/analysis`, { method: "PATCH", body: JSON.stringify(payload) }),
  generate: (id, caseTypes) =>
    api(`/requirements/${id}/generate`, { method: "POST", body: JSON.stringify({ case_types: caseTypes }) }),
  listCases: (id, filters) => {
    const params = new URLSearchParams();
    if (filters.case_type) params.set("case_type", filters.case_type);
    if (filters.review_status) params.set("review_status", filters.review_status);
    const qs = params.toString();
    return api(`/requirements/${id}/cases${qs ? "?" + qs : ""}`);
  },
  createCase: (requirementId, payload) =>
    api(`/requirements/${requirementId}/cases`, { method: "POST", body: JSON.stringify(payload) }),
  getStats: (requirementId) => api(`/requirements/${requirementId}/stats`),
  updateCase: (id, payload) => api(`/cases/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteCase: (id) => api(`/cases/${id}`, { method: "DELETE" }),
  importAcceptedCases: (requirementId) =>
    api("/knowledge/import-accepted-cases", { method: "POST", body: JSON.stringify({ requirement_id: requirementId }) }),
  uploadImages: async (requirementId, files) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    // 注意:上传走 multipart,不能带 application/json 头,让浏览器自动带 boundary
    const resp = await fetch(`${API_BASE}/requirements/${requirementId}/images`, { method: "POST", body: form });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new Error(body.detail || resp.statusText);
    }
    return resp.json();
  },
  deleteImage: (imageId) => api(`/requirements/images/${imageId}`, { method: "DELETE" }),
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
          <button class="requirement-item-delete" data-action="delete-req" title="删除需求">&times;</button>
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
  if (!item) return;
  const reqId = Number(item.dataset.reqId);
  // 点击删除按钮:阻止冒泡避免误触选中,二次确认后删除
  if (e.target.dataset.action === "delete-req") {
    e.stopPropagation();
    deleteRequirement(reqId);
    return;
  }
  selectRequirement(reqId);
});

async function deleteRequirement(id) {
  const req = state.requirements.find((r) => r.id === id);
  const title = req ? req.title : `#${id}`;
  if (!confirm(`确定删除需求「${title}」吗?该需求下的用例、需求理解结果、配图将一并删除,且无法恢复。`)) {
    return;
  }
  try {
    await Api.deleteRequirement(id);
    state.requirements = state.requirements.filter((r) => r.id !== id);
    if (state.selectedRequirement && state.selectedRequirement.id === id) {
      state.selectedRequirement = null;
      document.getElementById("requirement-detail").classList.add("hidden");
      document.getElementById("empty-state").classList.remove("hidden");
    }
    renderRequirementList();
    toast("需求已删除");
  } catch (err) {
    toast(`删除失败: ${err.message}`, true);
  }
}

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
  renderRequirementImages(req.images || []);

  const analysisSection = document.getElementById("analysis-section");
  if (req.analysis) {
    analysisSection.classList.remove("hidden");
    renderAnalysis(req.analysis);
  } else {
    analysisSection.classList.add("hidden");
  }
}

function renderRequirementImages(images) {
  const container = document.getElementById("req-images");
  if (!images || images.length === 0) {
    container.innerHTML = "";
    return;
  }
  container.innerHTML =
    `<div class="req-images-label">需求配图(${images.length})</div>` +
    images
      .map(
        (img) => `
        <a class="req-image-thumb" href="${img.url}" target="_blank" rel="noopener" title="${escapeHtml(img.filename)}">
          <img src="${img.url}" alt="${escapeHtml(img.filename)}" />
        </a>`
      )
      .join("");
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

// 从链接抓取来的来源信息,创建需求时一并提交,便于回溯需求出处
let importedSource = { source: "manual", source_ref_id: null };
// 新建需求时选中的配图(File 对象),创建成功后再统一上传
let selectedImages = [];

const MAX_IMAGES = 6;
const MAX_IMAGE_MB = 8;

document.getElementById("btn-new-requirement").addEventListener("click", () => {
  document.getElementById("input-req-link").value = "";
  document.getElementById("input-req-title").value = "";
  document.getElementById("input-req-content").value = "";
  document.getElementById("input-req-images").value = "";
  importedSource = { source: "manual", source_ref_id: null };
  selectedImages = [];
  renderImagePreview();
  openModal("modal-new-requirement");
});

document.getElementById("btn-pick-images").addEventListener("click", () => {
  document.getElementById("input-req-images").click();
});

document.getElementById("input-req-images").addEventListener("change", (e) => {
  for (const file of Array.from(e.target.files)) {
    if (selectedImages.length >= MAX_IMAGES) {
      toast(`最多选择 ${MAX_IMAGES} 张图片`, true);
      break;
    }
    if (file.size > MAX_IMAGE_MB * 1024 * 1024) {
      toast(`「${file.name}」超过 ${MAX_IMAGE_MB}MB,已跳过`, true);
      continue;
    }
    selectedImages.push(file);
  }
  e.target.value = ""; // 允许重复选择同一文件
  renderImagePreview();
});

function renderImagePreview() {
  const container = document.getElementById("image-preview");
  container.innerHTML = selectedImages
    .map(
      (f, i) => `
      <div class="image-thumb" data-img-index="${i}">
        <img src="${URL.createObjectURL(f)}" alt="${escapeHtml(f.name)}" />
        <button class="image-thumb-remove" data-action="remove-image" title="移除">&times;</button>
      </div>`
    )
    .join("");
}

document.getElementById("image-preview").addEventListener("click", (e) => {
  if (e.target.dataset.action === "remove-image") {
    const idx = Number(e.target.closest(".image-thumb").dataset.imgIndex);
    selectedImages.splice(idx, 1);
    renderImagePreview();
  }
});

document.getElementById("btn-fetch-link").addEventListener("click", async (e) => {
  const url = document.getElementById("input-req-link").value.trim();
  if (!url) {
    toast("请先粘贴文档链接", true);
    return;
  }
  e.target.disabled = true;
  e.target.textContent = "抓取中...";
  try {
    const doc = await Api.fetchLink(url);
    document.getElementById("input-req-title").value = doc.title || "";
    document.getElementById("input-req-content").value = doc.content || "";
    importedSource = { source: doc.source, source_ref_id: doc.source_ref_id };
    toast("已从链接导入,请确认内容后创建");
  } catch (err) {
    toast(`抓取失败: ${err.message}`, true);
  } finally {
    e.target.disabled = false;
    e.target.textContent = "抓取";
  }
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
    const req = await Api.createRequirement({ title, content, ...importedSource });
    if (selectedImages.length > 0) {
      try {
        await Api.uploadImages(req.id, selectedImages);
      } catch (err) {
        toast(`需求已创建,但图片上传失败: ${err.message}`, true);
      }
    }
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

// ---------------- 编辑需求理解结果 ----------------

const linesToList = (text) =>
  text
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

document.getElementById("btn-edit-analysis").addEventListener("click", () => {
  const analysis = state.selectedRequirement && state.selectedRequirement.analysis;
  if (!analysis) {
    toast("请先完成 AI 需求理解", true);
    return;
  }
  document.getElementById("edit-feature-points").value = (analysis.feature_points || []).join("\n");
  document.getElementById("edit-business-rules").value = (analysis.business_rules || []).join("\n");
  document.getElementById("edit-edge-cases").value = (analysis.edge_cases || []).join("\n");
  document.getElementById("edit-open-questions").value = (analysis.open_questions || []).join("\n");
  openModal("modal-edit-analysis");
});

document.getElementById("btn-save-analysis").addEventListener("click", async (e) => {
  const req = state.selectedRequirement;
  const payload = {
    feature_points: linesToList(document.getElementById("edit-feature-points").value),
    business_rules: linesToList(document.getElementById("edit-business-rules").value),
    edge_cases: linesToList(document.getElementById("edit-edge-cases").value),
    open_questions: linesToList(document.getElementById("edit-open-questions").value),
  };
  e.target.disabled = true;
  try {
    const updated = await Api.updateAnalysis(req.id, payload);
    state.selectedRequirement.analysis = updated;
    renderAnalysis(updated);
    closeModal("modal-edit-analysis");
    toast("需求理解结果已更新");
  } catch (err) {
    toast(`保存失败: ${err.message}`, true);
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
  // 统计基于全量用例(不受列表筛选影响),单独拉取
  try {
    const stats = await Api.getStats(req.id);
    renderCaseStats(stats);
  } catch (_) {
    /* 统计失败不阻塞用例列表展示 */
  }
}

function formatRate(rate) {
  return rate == null ? "—" : `${(rate * 100).toFixed(0)}%`;
}

function renderCaseStats(stats) {
  const container = document.getElementById("case-stats");
  if (!stats || stats.total === 0) {
    container.innerHTML = "";
    return;
  }
  const cards = [
    { label: "用例总数", value: stats.total, hint: `AI ${stats.ai_count} / 人工 ${stats.manual_count}` },
    {
      label: "采纳率",
      value: formatRate(stats.acceptance_rate),
      hint: `已采纳 ${stats.accepted} / 已审核 ${stats.reviewed}`,
      cls: "stat-accept",
    },
    {
      label: "召回率",
      value: formatRate(stats.recall_rate),
      hint: `AI 覆盖率(人工补 ${stats.manual_count} 条)`,
      cls: "stat-recall",
    },
    { label: "待审核", value: stats.pending, hint: `驳回 ${stats.rejected} / 编辑 ${stats.edited}` },
  ];
  container.innerHTML = cards
    .map(
      (c) => `
      <div class="stat-card ${c.cls || ""}">
        <div class="stat-value">${c.value}</div>
        <div class="stat-label">${c.label}</div>
        <div class="stat-hint">${escapeHtml(c.hint)}</div>
      </div>`
    )
    .join("");
}

function renderCaseTable() {
  document.getElementById("case-count").textContent = state.cases.length;
  const tbody = document.getElementById("case-table-body");

  if (state.cases.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:24px;">暂无用例</td></tr>`;
    return;
  }

  tbody.innerHTML = state.cases
    .map(
      (c) => `
      <tr data-case-id="${c.id}">
        <td class="col-id">${c.id}</td>
        <td class="case-title-cell" data-action="edit">${escapeHtml(c.title)}</td>
        <td class="col-type"><span class="type-tag">${CASE_TYPE_LABEL[c.case_type] || c.case_type}</span></td>
        <td class="col-source"><span class="source-tag source-${c.source}">${SOURCE_LABEL[c.source] || c.source}</span></td>
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

function fillCaseEditor(caseItem) {
  state.editingCase = JSON.parse(JSON.stringify(caseItem));
  document.getElementById("edit-case-title").value = state.editingCase.title || "";
  document.getElementById("edit-case-precondition").value = state.editingCase.precondition || "";
  document.getElementById("edit-case-type").value = state.editingCase.case_type || "functional";
  document.getElementById("edit-case-priority").value = state.editingCase.priority || "P1";
  document.getElementById("edit-case-review-status").value = state.editingCase.review_status || "pending";
  document.getElementById("edit-case-comment").value = state.editingCase.review_comment || "";
  renderStepsEditor();
  openModal("modal-edit-case");
}

function openCaseEditor(caseItem) {
  state.caseEditorMode = "edit";
  document.getElementById("edit-case-modal-title").textContent = "编辑用例";
  document.getElementById("btn-delete-case").classList.remove("hidden");
  fillCaseEditor(caseItem);
}

function openCaseCreator() {
  state.caseEditorMode = "create";
  document.getElementById("edit-case-modal-title").textContent = "新增用例(人工补充)";
  document.getElementById("btn-delete-case").classList.add("hidden");
  fillCaseEditor({
    title: "",
    precondition: "",
    steps: [{ step: "", expected: "" }],
    case_type: state.filters.case_type || "functional",
    priority: "P1",
    review_status: "accepted",
    review_comment: "",
  });
}

document.getElementById("btn-add-case").addEventListener("click", () => {
  if (!state.selectedRequirement) return;
  openCaseCreator();
});

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
    steps: collectStepsFromEditor().filter((s) => s.step || s.expected),
    case_type: document.getElementById("edit-case-type").value,
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
    if (state.caseEditorMode === "create") {
      await Api.createCase(state.selectedRequirement.id, payload);
    } else {
      await Api.updateCase(state.editingCase.id, payload);
    }
    closeModal("modal-edit-case");
    await refreshCases();
    toast(state.caseEditorMode === "create" ? "已新增用例" : "保存成功");
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

document.getElementById("btn-import-knowledge").addEventListener("click", async (e) => {
  const req = state.selectedRequirement;
  e.target.disabled = true;
  try {
    const result = await Api.importAcceptedCases(req.id);
    toast(
      `已导入 ${result.imported} 条到知识库(已存在跳过 ${result.skipped_existing} 条,该需求共有 ${result.total_accepted} 条已采纳用例)`
    );
  } catch (err) {
    toast(`导入失败: ${err.message}`, true);
  } finally {
    e.target.disabled = false;
  }
});

// ---------------- 初始化 ----------------

loadRequirements();
