/* ============================================================
 * graph.js — 用户知识图谱可视化 (vis-network)
 * 节点类型: User / Style / Product / Category
 * ============================================================ */

const GraphViz = {
  network: null,
  COLORS: {
    User: "#1677ff",
    Style: "#ff8a3d",
    Product: "#22c55e",
    Category: "#64748b"
  },

  /**
   * @param {object} graph  { nodes:[{id,label,type}], edges:[{source,target,relation}] }
   */
  render(graphData) {
    const container = document.getElementById("graphCanvas");
    const legend = document.getElementById("graphLegend");
    container.innerHTML = "";

    // 图例
    legend.innerHTML = Object.keys(this.COLORS).map(t =>
      `<span><span class="legend-dot" style="background:${this.COLORS[t]}"></span>${t}</span>`
    ).join("");

    if (!graphData || !graphData.nodes || graphData.nodes.length === 0) {
      container.innerHTML = '<div class="state-box"><div class="state-icon">🕸</div><p>暂无图谱数据（用户产生偏好后自动构建）</p></div>';
      return;
    }

    // 无 CDN 时降级提示
    if (typeof vis === "undefined" || !vis.Network) {
      container.innerHTML = '<div class="state-box error">vis-network 库未加载（请检查网络/CDN），原始数据如下：<br><br>' +
        '<pre style="text-align:left;font-size:12px;">' + esc(JSON.stringify(graphData, null, 2)) + '</pre></div>';
      return;
    }

    const nodes = graphData.nodes.map(n => ({
      id: String(n.id),
      label: n.label || String(n.id),
      group: n.type || "Product",
      color: { background: this.COLORS[n.type] || "#94a3b8", border: "#fff" },
      font: { color: "#fff", size: 14, face: "Microsoft YaHei" },
      shape: n.type === "User" ? "dot" : "box",
      size: n.type === "User" ? 22 : 16
    }));

    const edges = (graphData.edges || []).map(e => ({
      from: String(e.source),
      to: String(e.target),
      label: e.relation || "",
      arrows: "to",
      font: { size: 11, color: "#94a3b8", strokeWidth: 0, align: "middle" },
      color: { color: "#c5d3e8" }
    }));

    const dataSet = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
    const options = {
      physics: { stabilization: true, barnesHut: { gravitationalConstant: -3000 } },
      interaction: { hover: true, dragNodes: true, zoomView: true },
      edges: { smooth: true }
    };
    this.network = new vis.Network(container, dataSet, options);
  }
};

window.GraphViz = GraphViz;
