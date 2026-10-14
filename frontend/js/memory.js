/* ============================================================
 * memory.js — 用户记忆中心页逻辑
 * 三个 Tab: Chat Memory / LLM-Wiki / Knowledge-Graph
 * ============================================================ */

const MemoryPage = {
  cache: null,

  init() {
    // Tab 切换
    document.querySelectorAll("#memoryTabs .tab").forEach(t => {
      t.addEventListener("click", () => {
        document.querySelectorAll("#memoryTabs .tab").forEach(x => x.classList.remove("active"));
        t.classList.add("active");
        document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
        document.getElementById("tab-" + t.dataset.tab).classList.add("active");
        // 切到 graph tab 时再渲染（保证容器可见）
        if (t.dataset.tab === "graph" && this.cache) this.renderGraph();
      });
    });

    document.getElementById("memoryQueryBtn").addEventListener("click", () => this.query());
    document.getElementById("memoryUserId").addEventListener("keydown", e => {
      if (e.key === "Enter") this.query();
    });
    document.getElementById("memoryClearBtn").addEventListener("click", () => this.clear());
  },

  onShow() {
    // 切到本页时若已有缓存则不重复查询，否则自动查一次
    if (!this.cache) this.query();
  },

  async query() {
    const userId = document.getElementById("memoryUserId").value.trim() || "user_001";
    const loadBox = document.getElementById("memoryLoading");
    const errBox = document.getElementById("memoryError");
    errBox.hidden = true; loadBox.hidden = false;

    try {
      const d = await Api.getMemory(userId);
      this.cache = d;
      this.renderChat(d);
      this.renderWiki(d);
      this.renderGraph(d);
      toast("记忆加载成功", "ok");
    } catch (e) {
      errBox.hidden = false;
      errBox.textContent = e.message;
      this.cache = null;
    } finally {
      loadBox.hidden = true;
    }
  },

  async clear() {
    const userId = document.getElementById("memoryUserId").value.trim() || "user_001";
    if (!confirm("确认清除用户 " + userId + " 的全部记忆？此操作不可恢复。")) return;
    try {
      await Api.clearMemory(userId);
      toast("已清除该用户记忆", "ok");
      this.cache = null;
      this.renderChat(null); this.renderWiki(null);
      document.getElementById("graphCanvas").innerHTML =
        '<div class="state-box"><div class="state-icon">🧹</div><p>记忆已清除</p></div>';
    } catch (e) {
      toast(e.message, "err");
    }
  },

  /* ---- Chat Memory ---- */
  renderChat(d) {
    const list = document.getElementById("chatList");
    const arr = (d && (d.chat_memory || d.chat)) || [];
    if (!arr.length) {
      list.innerHTML = '<div class="state-box"><div class="state-icon">💬</div><p>暂无会话记忆（Redis TTL）</p></div>';
      return;
    }
    list.innerHTML = arr.map(m => {
      const role = m.role || "user";
      const ttl = m.ttl_remaining_sec ?? m.ttl ?? null;
      const ttlBar = ttl !== null
        ? `<div class="chat-ttl">TTL 剩余 ${ttl}s<div class="ttl-bar"><i style="width:${Math.min(100, ttl / 30)}%"></i></div></div>`
        : "";
      return `<div class="chat-item">
        <span class="chat-role ${role}">${role === "user" ? "用户" : "助手"}</span>
        <span class="chat-content">${esc(m.content || m.text || "-")}</span>
        ${ttlBar}
      </div>`;
    }).join("");
  },

  /* ---- LLM-Wiki ---- */
  renderWiki(d) {
    const list = document.getElementById("wikiList");
    const viewer = document.getElementById("wikiViewer");
    const arr = (d && (d.wiki_documents || d.wiki)) || [];
    if (!arr.length) {
      list.innerHTML = '<div class="state-box"><div class="state-icon">📄</div><p>暂无 Wiki 文档</p></div>';
      viewer.innerHTML = '<p class="muted">从左侧选择一篇 Wiki 文档查看内容</p>';
      return;
    }
    list.innerHTML = arr.map((w, i) => `
      <div class="wiki-item" data-i="${i}">
        <div>${esc(w.title || w.wiki_id || ("文档 " + (i + 1)))}</div>
        <div class="wid">${esc(w.wiki_id || "")} · ${esc(w.updated_at || "")}</div>
      </div>`).join("");

    list.querySelectorAll(".wiki-item").forEach(item => {
      item.onclick = () => {
        list.querySelectorAll(".wiki-item").forEach(x => x.classList.remove("active"));
        item.classList.add("active");
        const w = arr[parseInt(item.dataset.i, 10)];
        viewer.innerHTML = `<h4>${esc(w.title || w.wiki_id || "偏好文档")}</h4>
          <div class="wiki-md">${esc(w.content || w.body || "(空)")}</div>`;
      };
    });
    // 默认选中第一篇
    list.querySelector(".wiki-item")?.click();
  },

  /* ---- Knowledge-Graph ---- */
  renderGraph(d) {
    const g = d && (d.graph || d.knowledge_graph);
    // 后端可能返回 nodes/edges 也可能返回 relations 摘要
    if (!g) {
      // 尝试用记忆中的关系摘要拼一个简易图
      GraphViz.render({ nodes: [], edges: [] });
      return;
    }
    GraphViz.render(g);
  }
};

window.MemoryPage = MemoryPage;
window.addEventListener("DOMContentLoaded", () => MemoryPage.init());
