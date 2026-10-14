/* ============================================================
 * api.js  —  CLIP 电商多模态检索系统 后端 API 封装
 * 后端基础地址: http://localhost:8565
 * 统一响应: { code: 0, message: "success", data: {...} }
 * ============================================================ */

const API_BASE = "http://127.0.0.1:8565";

/** 商品图片完整 URL: /api/images/P001.jpg -> http://localhost:8565/api/images/P001.jpg */
function imageUrl(path) {
  if (!path) return "";
  if (path.startsWith("http")) return path;
  if (!path.startsWith("/")) path = "/" + path;
  return API_BASE + path;
}

/**
 * 统一请求封装
 * @param {string} path  如 /api/search
 * @param {object} opts  { method, body(JSON对象), form(FormData) }
 * @returns {Promise<any>}  resolve data 字段; reject Error(带 message)
 */
async function request(path, opts = {}) {
  const url = API_BASE + path;
  const fetchOpts = { method: opts.method || "GET" };

  if (opts.form) {
    fetchOpts.body = opts.form; // 浏览器自动带 multipart boundary
  } else if (opts.body !== undefined && opts.body !== null) {
    fetchOpts.headers = { "Content-Type": "application/json" };
    fetchOpts.body = JSON.stringify(opts.body);
  }

  let resp;
  try {
    resp = await fetch(url, fetchOpts);
  } catch (e) {
    throw new Error("无法连接后端服务 (" + API_BASE + ")，请确认后端已在 8565 端口启动。");
  }

  let json = null;
  try {
    json = await resp.json();
  } catch (e) {
    throw new Error("后端返回了非 JSON 数据 (HTTP " + resp.status + ")");
  }

  if (!resp.ok || (json && json.code !== 0)) {
    const msg = (json && json.message) ? json.message : ("HTTP " + resp.status);
    throw new Error(msg);
  }
  return json.data;
}

/* ---------------------- 业务接口 ---------------------- */

const Api = {
  BASE: API_BASE,

  /** 健康检查（不抛错，返回 boolean） */
  async health() {
    try {
      await request("/api/stats");
      return true;
    } catch (e) {
      return false;
    }
  },

  /** 1. 文本搜图 / 混合检索
   *  body: { query, user_id, mode:'text'|'hybrid', top_k, lambda } */
  search(body) {
    return request("/api/search", { method: "POST", body });
  },

  /** 2. 图搜图 (multipart) */
  searchImage(imageFile, { user_id = "user_001", top_k = 10, lambda = 0.7 } = {}) {
    const fd = new FormData();
    fd.append("image", imageFile);
    fd.append("user_id", user_id);
    fd.append("top_k", String(top_k));
    fd.append("lambda", String(lambda));
    return request("/api/search/image", { method: "POST", form: fd });
  },

  /** 3. 意图分析
   *  body: { user_id, text, image_url, session_id } */
  analyze(body) {
    return request("/api/analyze", { method: "POST", body });
  },

  /** 4. 语音转文本 (multipart) */
  voiceToText(audioFile, user_id = "user_001") {
    const fd = new FormData();
    fd.append("audio", audioFile);
    fd.append("user_id", user_id);
    return request("/api/voice", { method: "POST", form: fd });
  },

  /** 5a. 读取用户记忆 */
  getMemory(user_id) {
    return request("/api/memory?user_id=" + encodeURIComponent(user_id));
  },

  /** 5b. 写入用户记忆  body:{ user_id, type, content } */
  writeMemory(body) {
    return request("/api/memory", { method: "POST", body });
  },

  /** 5c. 清除用户记忆 */
  clearMemory(user_id) {
    return request("/api/memory?user_id=" + encodeURIComponent(user_id), { method: "DELETE" });
  },

  /** 6. 系统状态 */
  stats() {
    return request("/api/stats");
  },

  /** 8. 双Agent协同演示 */
  demoCollaboration(body) {
    return request("/api/demo/collaboration", { method: "POST", body });
  },

  /** 9a. 重新入库 */
  reindex() {
    return request("/api/admin/reindex", { method: "POST", body: {} });
  },

  /** 9b. 分页商品列表 */
  products(page = 1, size = 20) {
    return request("/api/admin/products?page=" + page + "&size=" + size);
  },
};

/* 暴露到全局 */
window.Api = Api;
window.imageUrl = imageUrl;
