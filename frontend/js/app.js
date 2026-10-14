/* ============================================================
 * app.js — 主应用：页面切换、健康检查、Toast、架构图渲染
 * ============================================================ */

/* ---------- Toast ---------- */
let toastTimer = null;
function toast(msg, type = "") {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast show " + type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = "toast " + type; }, 2600);
}
window.toast = toast;

/* ---------- 页面切换 ---------- */
function switchPage(page) {
  document.querySelectorAll(".nav-item").forEach(li => {
    li.classList.toggle("active", li.dataset.page === page);
  });
  document.querySelectorAll(".page").forEach(pg => {
    pg.classList.toggle("active", pg.id === "page-" + page);
  });
  // 切到系统状态页时立即刷新
  if (page === "stats" && window.StatsPage) window.StatsPage.refresh();
  // 切到记忆中心时若已有用户ID则自动查询
  if (page === "memory" && window.MemoryPage) window.MemoryPage.onShow();
}

document.querySelectorAll(".nav-item").forEach(li => {
  li.addEventListener("click", () => switchPage(li.dataset.page));
});

/* ---------- 健康检查（每5秒） ---------- */
async function checkHealth() {
  const dot = document.getElementById("healthDot");
  const txt = document.getElementById("healthText");
  const ok = await Api.health();
  dot.className = "dot " + (ok ? "online" : "offline");
  txt.textContent = ok ? "后端已连接" : "后端未连接";
  return ok;
}
setInterval(checkHealth, 5000);

/* ---------- 工具：转义 HTML ---------- */
function esc(s) {
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
window.esc = esc;

/* ---------- 渲染商品卡片（检索页 & 演示页共用） ---------- */
function renderProductCard(p) {
  const img = p.image_url ? imageUrl(p.image_url) : "";
  const clip = (p.clip_score !== undefined) ? (p.clip_score * 100).toFixed(1) : null;
  const graph = (p.graph_score !== undefined) ? (p.graph_score * 100).toFixed(1) : null;
  const final = (p.final_score !== undefined) ? (p.final_score * 100).toFixed(1) : null;
  const price = (p.price !== undefined) ? ("¥" + Number(p.price).toLocaleString()) : "—";

  const imgHtml = img
    ? `<div class="pc-img" style="background-image:url('${esc(img)}')"
         onclick="event.stopPropagation();this.querySelector('.ph')?.remove()"></div>`
    : `<div class="pc-img"><div class="ph">📦</div></div>`;

  let scoreHtml = "";
  if (final !== null) {
    scoreHtml = `
      <div class="pc-scores">
        <div class="score-row"><span class="lbl">CLIP相似度</span>
          <span class="bar clip"><i style="width:${clip}%"></i></span><span class="val">${clip}</span></div>
        <div class="score-row"><span class="lbl">图谱偏好分</span>
          <span class="bar graph"><i style="width:${graph}%"></i></span><span class="val">${graph}</span></div>
        <div class="score-row"><span class="lbl">综合得分</span>
          <span class="bar final"><i style="width:${final}%"></i></span><span class="val">${final}</span></div>
      </div>`;
  }

  return `
    <div class="product-card" data-pid="${esc(p.product_id || "")}">
      ${imgHtml}
      <div class="pc-body">
        <div class="pc-title">${esc(p.title || "未命名商品")}</div>
        <div class="pc-price">${price}</div>
        <div class="pc-tags">
          ${p.category ? `<span class="tag cat">${esc(p.category)}</span>` : ""}
          ${p.style ? `<span class="tag style">${esc(p.style)}</span>` : ""}
          ${p.color ? `<span class="tag">${esc(p.color)}</span>` : ""}
        </div>
        ${scoreHtml}
      </div>
      <div class="pc-detail">
        <div class="kv"><b>商品ID</b><span>${esc(p.product_id || "-")}</span></div>
        <div class="kv"><b>描述</b><span>${esc(p.description || "-")}</span></div>
        <div class="kv"><b>材质</b><span>${esc(p.material || "-")}</span></div>
        <div class="kv"><b>颜色</b><span>${esc(p.color || "-")}</span></div>
      </div>
    </div>`;
}

/** 绑定卡片点击展开详情 */
function bindCardToggle(containerId) {
  const c = document.getElementById(containerId);
  if (!c) return;
  c.querySelectorAll(".product-card").forEach(card => {
    card.onclick = () => card.classList.toggle("open");
  });
}
window.renderProductCard = renderProductCard;
window.bindCardToggle = bindCardToggle;

/* ---------- 架构图渲染 ---------- */
function renderArch() {
  const box = (title, sub, cls = "") =>
    `<div class="arch-box ${cls}"><div class="ab-title">${title}</div><div class="ab-sub">${sub}</div></div>`;
  const arrow = (lbl = "") =>
    `<div class="arch-arrow">↓<span class="lbl">${lbl}</span></div>`;

  document.getElementById("archDiagram").innerHTML = `
    <!-- 用户输入层 -->
    <div class="arch-layer">
      <div class="arch-layer-title">① 用户输入层</div>
      <div class="arch-row">
        ${box("📝 文本查询", "自然语言描述")}
        ${box("🖼️ 参考图片", "以图搜图")}
        ${box("🎤 语音输入", "Whisper 转文本")}
      </div>
    </div>
    ${arrow("多模态统一输入")}

    <!-- 双Agent + 共享记忆 -->
    <div class="arch-layer">
      <div class="arch-layer-title">② 双 Agent 协同 + 共享记忆中心</div>
      <div class="arch-row">
        <div style="display:flex;flex-direction:column;gap:8px;align-items:center;">
          ${box("🧠 意图分析 Agent", "提取偏好 / 写Wiki / 更新图谱", "agent")}
          ${box("🔎 检索实现 Agent", "订阅信号 / 拉取Wiki / Cypher / CLIP召回", "agent")}
        </div>
        <div class="arch-memory" style="flex:1;flex-direction:column;justify-content:center;">
          <div style="font-size:12px;color:#16a34a;font-weight:600;text-align:center;">共享记忆中心 (TencentDB-Agent-Memory 规范)</div>
          <div class="arch-row">
            ${box("Redis", "Chat Memory · TTL会话记忆", "store")}
            ${box("PostgreSQL", "LLM-Wiki · Markdown偏好文档", "store")}
            ${box("Neo4j", "Knowledge-Graph · 用户-商品-风格", "store")}
          </div>
        </div>
      </div>
    </div>
    ${arrow("λ·cos(文本,图像) + (1-λ)·W_graph(用户,风格)")}

    <!-- 向量检索层 -->
    <div class="arch-layer">
      <div class="arch-layer-title">③ 多模态对齐与向量检索层</div>
      <div class="arch-row">
        ${box("Chinese-CLIP ViT-B/16", "图文统一映射 512维")}
        ${box("Milvus Lite", "商品向量库 · 近似最近邻")}
        ${box("混合评分融合", "CLIP相似度 + 图谱偏好")}
      </div>
    </div>
    ${arrow("结构化结果")}

    <!-- 前端展示层 -->
    <div class="arch-layer">
      <div class="arch-layer-title">④ 前端展示层 (本系统 :8525)</div>
      <div class="arch-row">
        ${box("商品卡片网格", "相似度进度条可视化")}
        ${box("记忆图谱交互", "vis-network 可拖拽")}
        ${box("Agent轨迹回放", "双Agent分步演示")}
      </div>
    </div>
  `;
}

/* ---------- 系统状态页 ---------- */
const StatsPage = {
  timer: null,
  async refresh() {
    const grid = document.getElementById("statGrid");
    const errBox = document.getElementById("statsError");
    const loadBox = document.getElementById("statsLoading");
    try {
      const d = await Api.stats();
      errBox.hidden = true;
      loadBox.hidden = true;
      document.getElementById("statsTime").textContent =
        "每 5 秒自动刷新 · 更新于 " + new Date().toLocaleTimeString();

      const card = (label, value, sub, ok) => {
        const v = (ok === undefined) ? value :
          `<span class="${ok ? "badge-ok" : "badge-no"}">${value}</span>`;
        return `<div class="stat-card">
          <div class="sc-label">${label}</div>
          <div class="sc-value">${v}</div>
          <div class="sc-sub">${sub}</div></div>`;
      };

      grid.innerHTML =
        card("Milvus 商品数量", d.milvus_products ?? "-", "已入库向量条数") +
        card("Wiki 文档数量", d.wiki_documents ?? "-", "PostgreSQL 偏好文档") +
        card("图谱节点 / 边",
          (d.graph_nodes ?? "-") + " / " + (d.graph_edges ?? "-"),
          "Neo4j 实体与关系") +
        card("CLIP 模型", d.clip_model_loaded ? "已加载" : "未加载",
          "Chinese-CLIP ViT-B/16", d.clip_model_loaded) +
        card("Ollama", d.ollama_connected ? "已连接" : "未连接",
          "LLM 推理服务", d.ollama_connected) +
        card("GPU", d.gpu_available ? "可用" : "不可用",
          "显存占用 " + (d.gpu_memory_used_mb ?? "-") + " MB", d.gpu_available);
    } catch (e) {
      loadBox.hidden = true;
      errBox.hidden = false;
      errBox.textContent = e.message;
      grid.innerHTML = "";
    }
  },
  start() {
    this.refresh();
    clearInterval(this.timer);
    this.timer = setInterval(() => this.refresh(), 5000);
  }
};
window.StatsPage = StatsPage;

/* ---------- 启动 ---------- */
window.addEventListener("DOMContentLoaded", () => {
  renderArch();
  checkHealth();
  StatsPage.start();
});
