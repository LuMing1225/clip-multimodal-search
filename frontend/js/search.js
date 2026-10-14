/* ============================================================
 * search.js — 多模态检索页逻辑
 * ============================================================ */

const SearchPage = {
  uploadedImage: null, // File 对象

  init() {
    // λ 滑块
    const slider = document.getElementById("lambdaSlider");
    const lv = document.getElementById("lambdaVal");
    slider.addEventListener("input", () => { lv.textContent = slider.value; });

    // 模式切换样式
    document.querySelectorAll("input[name=searchMode]").forEach(r => {
      r.addEventListener("change", () => {
        document.querySelectorAll(".mode-opt").forEach(o => {
          o.classList.toggle("checked", o.querySelector("input").checked);
        });
      });
    });

    this.bindImageUpload();
    this.bindVoiceUpload();
    document.getElementById("searchBtn").addEventListener("click", () => this.doSearch());

    // 回车快捷检索
    document.getElementById("searchQuery").addEventListener("keydown", e => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) this.doSearch();
    });
  },

  /* ---- 图片上传 ---- */
  bindImageUpload() {
    const drop = document.getElementById("imageDrop");
    const input = document.getElementById("imageInput");
    const thumb = document.getElementById("imageThumb");
    const thumbImg = document.getElementById("imageThumbImg");

    drop.addEventListener("click", e => {
      if (e.target.id === "imageRemove") return;
      input.click();
    });
    input.addEventListener("change", () => { if (input.files[0]) this.setImg(input.files[0]); });

    ["dragover", "dragenter"].forEach(ev =>
      drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("dragover"); }));
    ["dragleave", "drop"].forEach(ev =>
      drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("dragover"); }));
    drop.addEventListener("drop", e => {
      const f = e.dataTransfer.files[0];
      if (f && f.type.startsWith("image/")) this.setImg(f);
    });

    document.getElementById("imageRemove").addEventListener("click", e => {
      e.stopPropagation();
      this.uploadedImage = null;
      input.value = "";
      thumb.hidden = true;
    });

    this._setImg = (file) => {
      this.uploadedImage = file;
      thumbImg.src = URL.createObjectURL(file);
      thumb.hidden = false;
    };
  },
  setImg(f) { this._setImg(f); },

  /* ---- 语音上传 ---- */
  bindVoiceUpload() {
    const drop = document.getElementById("voiceDrop");
    const input = document.getElementById("voiceInput");
    drop.addEventListener("click", () => input.click());
    input.addEventListener("change", async () => {
      if (!input.files[0]) return;
      const f = input.files[0];
      document.getElementById("voiceName").textContent = "识别中… " + f.name;
      try {
        const userId = document.getElementById("searchUserId").value.trim() || "user_001";
        const data = await Api.voiceToText(f, userId);
        document.getElementById("searchQuery").value = data.text || "";
        document.getElementById("voiceName").textContent = "✓ 已转写: " + (data.text || "");
        toast("语音转文本成功", "ok");
      } catch (e) {
        document.getElementById("voiceName").textContent = "转写失败";
        toast(e.message, "err");
      }
    });
  },

  /* ---- 执行检索 ---- */
  async doSearch() {
    const userId = document.getElementById("searchUserId").value.trim() || "user_001";
    const query = document.getElementById("searchQuery").value.trim();
    const mode = document.querySelector("input[name=searchMode]:checked").value;
    const topK = parseInt(document.getElementById("topkSelect").value, 10);
    const lambda = parseFloat(document.getElementById("lambdaSlider").value);

    const grid = document.getElementById("productGrid");
    const empty = document.getElementById("searchEmpty");
    const loading = document.getElementById("searchLoading");
    const errBox = document.getElementById("searchError");
    const meta = document.getElementById("resultMeta");

    if (!query && !this.uploadedImage) {
      toast("请输入文本或上传图片", "err");
      return;
    }

    // 状态切换
    empty.hidden = true; errBox.hidden = true; meta.hidden = true;
    loading.hidden = false; grid.innerHTML = "";
    const btn = document.getElementById("searchBtn");
    btn.disabled = true; btn.textContent = "检索中…";

    try {
      let data;
      if (this.uploadedImage) {
        data = await Api.searchImage(this.uploadedImage, {
          user_id: userId, top_k: topK, lambda
        });
      } else {
        data = await Api.search({
          query, user_id: userId, mode, top_k: topK, lambda
        });
      }

      const results = data.results || [];
      document.getElementById("resultLatency").textContent = data.latency_ms ?? "-";
      document.getElementById("resultCount").textContent = results.length;
      meta.hidden = false;

      if (results.length === 0) {
        empty.hidden = false;
        empty.innerHTML = '<div class="state-icon">🔍</div><p>未检索到相关商品，换个关键词试试</p>';
      } else {
        grid.innerHTML = results.map(renderProductCard).join("");
        bindCardToggle("productGrid");
      }
    } catch (e) {
      errBox.hidden = false;
      errBox.textContent = e.message;
    } finally {
      loading.hidden = true;
      btn.disabled = false; btn.textContent = "🚀 开始检索";
    }
  }
};

window.addEventListener("DOMContentLoaded", () => SearchPage.init());
