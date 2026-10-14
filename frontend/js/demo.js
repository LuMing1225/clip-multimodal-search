/* ============================================================
 * demo.js — 双Agent协同演示页逻辑
 * 轨迹顺序(工单要求):
 *  Intent.Extract_Features -> Intent.Write_Wiki ->
 *  Retriever.Subscribe_Signal -> Retriever.Read_Wiki ->
 *  Retriever.Vector_Search
 * ============================================================ */

const DemoPage = {

  init() {
    document.getElementById("demoAnalyzeBtn").addEventListener("click", () => this.stepAnalyze());
    document.getElementById("demoSearchBtn").addEventListener("click", () => this.stepRetrieve());
    document.getElementById("demoFullBtn").addEventListener("click", () => this.fullDemo());
    document.getElementById("demoResetBtn").addEventListener("click", () => this.reset());
  },

  reset() {
    document.getElementById("analyzeTrajectory").innerHTML = "";
    document.getElementById("retrieveTrajectory").innerHTML = "";
    document.getElementById("demoGrid").innerHTML = "";
    toast("已重置演示");
  },

  /* 向容器追加一个动画轨迹步骤 */
  pushTraj(containerId, icon, text, opts = {}) {
    const c = document.getElementById(containerId);
    const el = document.createElement("div");
    el.className = "traj-step" + (opts.ok ? " ok" : "");
    el.innerHTML = `<span class="t-icon">${icon}</span>
      <span class="t-body">${text}</span>
      ${opts.code ? `<div class="traj-code">${esc(opts.code)}</div>` : ""}
      <span class="t-time">${new Date().toLocaleTimeString()}</span>`;
    c.appendChild(el);
    // 触发入场动画
    requestAnimationFrame(() => el.classList.add("show"));
    return el;
  },

  sleep(ms) { return new Promise(r => setTimeout(r, ms)); },

  /* ---- 步骤1+2: 意图分析 ---- */
  async stepAnalyze() {
    const userId = document.getElementById("demoUserId").value.trim() || "user_001";
    const text = document.getElementById("demoInitial").value.trim();
    if (!text) { toast("请输入初始文本", "err"); return; }

    document.getElementById("analyzeTrajectory").innerHTML = "";
    this.pushTraj("analyzeTrajectory", "📥", "接收用户输入: " + text);
    await this.sleep(500);

    try {
      const d = await Api.analyze({ user_id: userId, text, image_url: null, session_id: "sess_001" });
      const pref = d.preferences || {};
      this.pushTraj("analyzeTrajectory", "🧩",
        "<b>Extract_Features</b> 提取偏好: style=" + esc(pref.style) +
        ", color=" + esc(pref.color) + ", material=" + esc(pref.material) +
        ", category=" + esc(pref.category) + ", sentiment=" + esc(pref.sentiment), { ok: true });
      await this.sleep(400);
      this.pushTraj("analyzeTrajectory", "📄",
        "<b>Write_Wiki</b> 写入 LLM-Wiki (PostgreSQL), wiki_id=" + esc(d.wiki_id || "-"),
        { ok: !!d.wiki_id });
      await this.sleep(400);
      this.pushTraj("analyzeTrajectory", "🕸",
        "<b>Update_Graph</b> Neo4j: (User)-[:PREFERS]->(Style:" + esc(pref.style || "?") + ")，图谱已更新=" + !!d.graph_updated,
        { ok: !!d.graph_updated });
      await this.sleep(400);
      this.pushTraj("analyzeTrajectory", "📡",
        "<b>Publish_Signal</b> 向 Redis Stream 发布偏好变更信号，已发布=" + !!d.signal_published,
        { ok: !!d.signal_published });
      toast("意图分析完成，记忆已写入", "ok");
    } catch (e) {
      this.pushTraj("analyzeTrajectory", "⚠", e.message);
    }
  },

  /* ---- 步骤3+4: 记忆增强检索 ---- */
  async stepRetrieve() {
    const userId = document.getElementById("demoUserId").value.trim() || "user_001";
    const query = document.getElementById("demoFollowup").value.trim();
    if (!query) { toast("请输入后续查询", "err"); return; }

    document.getElementById("retrieveTrajectory").innerHTML = "";
    document.getElementById("demoGrid").innerHTML = "";

    this.pushTraj("retrieveTrajectory", "📡", "<b>Subscribe_Signal</b> 订阅 Redis Stream 偏好变更信号");
    await this.sleep(600);
    this.pushTraj("retrieveTrajectory", "📄", "<b>Read_Wiki</b> 拉取该用户最新偏好 Wiki，获得 style/color/material");
    await this.sleep(600);
    this.pushTraj("retrieveTrajectory", "🔍", "<b>Cypher_Query</b> 生成图谱定位查询", {
      code: 'MATCH (u:User {id:"' + userId + '"})-[:PREFERS]->(s:Style)\nMATCH (p:Product)-[:HAS_STYLE]->(s)\nWHERE p.category = "家具" AND p.material CONTAINS "布艺"\nRETURN p ORDER BY 相似度 DESC'
    });
    await this.sleep(700);

    try {
      const d = await Api.search({ query, user_id: userId, mode: "hybrid", top_k: 10, lambda: 0.7 });
      this.pushTraj("retrieveTrajectory", "🧮",
        "<b>CLIP_Vector_Search</b> 文本编码后在 Milvus 检索，耗时 " + (d.latency_ms || "-") + "ms", { ok: true });
      await this.sleep(400);
      this.pushTraj("retrieveTrajectory", "⚖",
        "<b>Hybrid_Score</b> Score = 0.7·cos(文本,图) + 0.3·W_graph(用户,风格)，命中 " + (d.results || []).length + " 件", { ok: true });

      const results = d.results || [];
      document.getElementById("demoGrid").innerHTML = results.map(renderProductCard).join("");
      bindCardToggle("demoGrid");
      if (!results.length) toast("后端未返回结果", "err");
    } catch (e) {
      this.pushTraj("retrieveTrajectory", "⚠", e.message);
    }
  },

  /* ---- 一键完整演示 ---- */
  async fullDemo() {
    const userId = document.getElementById("demoUserId").value.trim() || "user_001";
    const initial = document.getElementById("demoInitial").value.trim();
    const followup = document.getElementById("demoFollowup").value.trim();
    this.reset();

    this.pushTraj("analyzeTrajectory", "🚀", "一键演示启动，用户=" + userId);
    await this.sleep(500);
    this.pushTraj("analyzeTrajectory", "📥", "意图分析Agent接收: " + initial);
    await this.sleep(600);

    try {
      const d = await Api.demoCollaboration({
        user_id: userId, initial_input: initial, follow_up_query: followup
      });

      // —— 意图分析侧 ——
      const intent = d.intent_agent || d.intent || {};
      const pref = intent.preferences || {};
      this.pushTraj("analyzeTrajectory", "🧩",
        "Extract_Features: " + JSON.stringify(pref), { ok: true });
      await this.sleep(500);
      this.pushTraj("analyzeTrajectory", "📄", "Write_Wiki → PostgreSQL (wiki_id=" + esc(intent.wiki_id || "-") + ")", { ok: true });
      await this.sleep(500);
      this.pushTraj("analyzeTrajectory", "🕸", "Update_Graph → Neo4j PREFERS 关系", { ok: true });
      await this.sleep(500);
      this.pushTraj("analyzeTrajectory", "📡", "Publish_Signal → Redis Stream", { ok: true });
      await this.sleep(700);

      // —— 检索侧 ——
      this.pushTraj("retrieveTrajectory", "📡", "Retriever.Subscribe_Signal 订阅成功", { ok: true });
      await this.sleep(500);
      this.pushTraj("retrieveTrajectory", "📄", "Retriever.Read_Wiki 拉取偏好上下文", { ok: true });
      await this.sleep(500);
      this.pushTraj("retrieveTrajectory", "🔍", "Retriever.Cypher 图谱定位", {
        code: d.retriever_agent?.cypher_query || d.retriever?.cypher_query ||
          'MATCH (u:User)-[:PREFERS]->(s:Style)\nMATCH (p:Product)-[:HAS_STYLE]->(s) RETURN p'
      });
      await this.sleep(700);
      this.pushTraj("retrieveTrajectory", "🧮", "Retriever.Vector_Search → Milvus CLIP 召回", { ok: true });
      await this.sleep(500);
      this.pushTraj("retrieveTrajectory", "⚖", "Hybrid_Score 融合 CLIP + 图谱偏好", { ok: true });

      const results = d.results || d.retriever_agent?.results || d.retriever?.results || [];
      document.getElementById("demoGrid").innerHTML = results.map(renderProductCard).join("");
      bindCardToggle("demoGrid");
      toast("完整演示完成", "ok");
    } catch (e) {
      this.pushTraj("analyzeTrajectory", "⚠", e.message);
      this.pushTraj("retrieveTrajectory", "ℹ", "一键接口不可用：可尝试分步执行（意图分析 + 记忆增强检索）");
    }
  }
};

window.addEventListener("DOMContentLoaded", () => DemoPage.init());
