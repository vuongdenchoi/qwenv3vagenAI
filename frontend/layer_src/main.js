// main.js — UI controller cho Qwen Layer Extractor (fal.ai)

import { uploadToFal, decomposeImage } from "./fal.js";
import { downloadAllAsZip, downloadSingleLayer } from "./zipper.js";

// ── State ─────────────────────────────────────────────────────────────
let currentFile   = null;
let currentBase64 = null;
let currentLayers = [];   // [{ url, index, label }]
let originalFilename = "image";

// ── DOM refs ──────────────────────────────────────────────────────────
const fileInput       = document.getElementById("fileInput");
const dropzone        = document.getElementById("dropzone");
const dropIcon        = document.getElementById("dropIcon");
const dropText        = document.getElementById("dropText");
const runBtn          = document.getElementById("runBtn");
const downloadAllBtn  = document.getElementById("downloadAllBtn");
const resetBtn        = document.getElementById("resetBtn");
const logBox          = document.getElementById("logBox");
const resultsSection  = document.getElementById("resultsSection");
const layersGrid      = document.getElementById("layersGrid");
const layerCount      = document.getElementById("layerCount");
const progressWrap    = document.getElementById("progressWrap");
const progressBar     = document.getElementById("progressBar");
const previewWrap     = document.getElementById("previewWrap");
const previewImg      = document.getElementById("previewImg");
const previewInfo     = document.getElementById("previewInfo");

// Slider refs
const numLayersInput     = document.getElementById("numLayers");
const inferStepsInput    = document.getElementById("inferSteps");
const guidanceScaleInput = document.getElementById("guidanceScale");
const numLayersVal       = document.getElementById("numLayersVal");
const inferStepsVal      = document.getElementById("inferStepsVal");
const guidanceScaleVal   = document.getElementById("guidanceScaleVal");
const autoDetectInput    = document.getElementById("autoDetect");
const qwenAnalysisPanel  = document.getElementById("qwenAnalysisPanel");

// ── Slider sync ───────────────────────────────────────────────────────
numLayersInput.addEventListener("input", () => {
  numLayersVal.textContent = numLayersInput.value;
});
inferStepsInput.addEventListener("input", () => {
  inferStepsVal.textContent = inferStepsInput.value;
});
guidanceScaleInput.addEventListener("input", () => {
  guidanceScaleVal.textContent = parseFloat(guidanceScaleInput.value).toFixed(1);
});

// Toggle slider state based on auto-detect checkbox
function updateSliderStates() {
  const isAuto = autoDetectInput.checked;
  [numLayersInput, inferStepsInput, guidanceScaleInput].forEach(input => {
    input.disabled = isAuto;
    const field = input.closest(".field");
    if (field) {
      if (isAuto) {
        field.classList.add("slider-disabled");
      } else {
        field.classList.remove("slider-disabled");
      }
    }
  });
}
autoDetectInput.addEventListener("change", updateSliderStates);

// ── Log helper ────────────────────────────────────────────────────────
function log(msg, type = "info") {
  logBox.style.display = "block";
  const line = document.createElement("div");
  line.className = `line ${type}`;
  line.textContent = "> " + msg;
  logBox.appendChild(line);
  logBox.scrollTop = logBox.scrollHeight;
}
function clearLog() {
  logBox.innerHTML = "";
  logBox.style.display = "none";
}

// ── Progress ──────────────────────────────────────────────────────────
function setProgress(pct) {
  progressWrap.style.display = "block";
  progressBar.style.width = pct + "%";
}
function hideProgress() {
  progressWrap.style.display = "none";
  progressBar.style.width = "0%";
}

// ── File handling ─────────────────────────────────────────────────────
async function handleFile(file) {
  if (!file?.type.startsWith("image/")) {
    log("File không hợp lệ! Chỉ chấp nhận ảnh PNG/JPG/WEBP.", "err");
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    log("File quá lớn! Tối đa 10MB.", "err");
    return;
  }

  currentFile = file;
  originalFilename = file.name.replace(/\.[^.]+$/, "") || "image";

  // Convert to base64
  currentBase64 = await toBase64(file);

  // Show preview
  const objectUrl = URL.createObjectURL(file);
  previewImg.src = objectUrl;
  previewImg.onload = () => {
    const w = previewImg.naturalWidth;
    const h = previewImg.naturalHeight;
    previewInfo.innerHTML = `
      <strong>${file.name}</strong><br>
      Kích thước: ${w} × ${h}px<br>
      Dung lượng: ${(file.size / 1024).toFixed(0)} KB<br>
      Loại: ${file.type}
    `;
    URL.revokeObjectURL(objectUrl);
  };
  previewWrap.style.display = "flex";

  // Update dropzone
  dropIcon.textContent = "✅";
  dropText.textContent = file.name;

  runBtn.disabled = false;
  log(`Đã tải ảnh: ${file.name} (${(file.size / 1024).toFixed(0)} KB)`, "ok");
}

function toBase64(file) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result.split(",")[1]);
    r.onerror = rej;
    r.readAsDataURL(file);
  });
}

// ── Main pipeline ─────────────────────────────────────────────────────
async function runPipeline() {
  const apiKey = document.getElementById("falKey").value.trim();

  if (!currentFile || !currentBase64) {
    log("Chưa chọn ảnh!", "err");
    return;
  }
  if (!apiKey) {
    log("Chưa nhập fal.ai API key!", "err");
    return;
  }

  const autoDetect       = autoDetectInput.checked;
  const numLayers        = parseInt(numLayersInput.value);
  const numInferSteps    = parseInt(inferStepsInput.value);
  const guidanceScale    = parseFloat(guidanceScaleInput.value);

  // Reset UI
  runBtn.disabled = true;
  downloadAllBtn.disabled = true;
  clearLog();
  layersGrid.innerHTML = "";
  resultsSection.style.display = "none";
  qwenAnalysisPanel.innerHTML = "";
  qwenAnalysisPanel.style.display = "none";
  currentLayers = [];
  setProgress(5);

  try {
    // ── Bước 1: Upload ảnh ─────────────────────────────
    log("📤 Đang upload ảnh lên fal.ai storage...", "info");
    setProgress(15);

    const imageUrl = await uploadToFal(currentBase64, currentFile.type, apiKey);
    log(`✅ Upload thành công: ${imageUrl.slice(0, 60)}...`, "ok");
    setProgress(25);

    // ── Bước 2: Decompose ──────────────────────────────
    log(autoDetect ? "🔍 Đang gửi yêu cầu tới backend phân tích bằng Qwen3-VL..." : `🔍 Gửi yêu cầu decompose: ${numLayers} layers, ${numInferSteps} steps...`, "info");
    log("⏳ Thường mất 15-45 giây, vui lòng chờ...", "warn");

    let pollCount = 0;
    const result = await decomposeImage(imageUrl, apiKey, {
      numLayers,
      guidanceScale,
      numInferenceSteps: numInferSteps,
      autoDetect
    }, (statusMsg) => {
      log(statusMsg, "info");
      pollCount++;
      // Animate progress từ 25 → 85 trong khi poll
      const pct = Math.min(85, 25 + pollCount * 4);
      setProgress(pct);
    });

    const layers = result.layers || [];
    setProgress(90);
    log(`✅ Nhận được ${layers.length} layer(s)!`, "ok");

    currentLayers = layers;

    // ── Hiển thị kết quả phân tích Qwen3-VL ──────────────
    if (result.qwen_analysis) {
      const qa = result.qwen_analysis;
      
      // Cập nhật giá trị hiển thị trên slider
      numLayersInput.value = qa.num_layers;
      numLayersVal.textContent = qa.num_layers;
      
      inferStepsInput.value = qa.num_inference_steps;
      inferStepsVal.textContent = qa.num_inference_steps;
      
      guidanceScaleInput.value = qa.guidance_scale;
      guidanceScaleVal.textContent = parseFloat(qa.guidance_scale).toFixed(1);
      
      // Render analysis panel
      qwenAnalysisPanel.innerHTML = `
        <div class="qwen-analysis-header">
          <span>✨ Phân Tích & Tối Ưu Tham Số Bởi Qwen3-VL</span>
        </div>
        <div class="qwen-analysis-body">
          ${qa.reason}
        </div>
        <div class="qwen-analysis-params">
          <span class="qwen-param-badge">📊 Layer: ${qa.num_layers}</span>
          <span class="qwen-param-badge">⚡ Guidance: ${parseFloat(qa.guidance_scale).toFixed(1)}</span>
          <span class="qwen-param-badge">🔄 Steps: ${qa.num_inference_steps}</span>
        </div>
      `;
      qwenAnalysisPanel.style.display = "flex";
      log(`[AI Auto-Detect] Qwen3-VL đã chọn: ${qa.num_layers} layers, guidance ${qa.guidance_scale}, steps ${qa.num_inference_steps}`, "ok");
    }

    // ── Bước 3: Render cards ───────────────────────────
    resultsSection.style.display = "block";
    layerCount.textContent = `${layers.length} layers`;

    for (const layer of layers) {
      renderLayerCard(layer);
    }

    setProgress(100);
    log(`\n🎉 Hoàn thành! ${layers.length} layer đã được tách.`, "ok");
    log(`💰 Chi phí ước tính: ~$0.05/lần decompose`, "info");

    downloadAllBtn.disabled = false;

    setTimeout(hideProgress, 1000);

  } catch (err) {
    log("❌ Lỗi: " + err.message, "err");
    console.error(err);
    hideProgress();
  }

  runBtn.disabled = false;
}

// ── Render layer card ─────────────────────────────────────────────────
function renderLayerCard(layer) {
  const { index, url, label } = layer;
  const cardIndex = index + 1;
  const filename = `${originalFilename}_layer_${String(cardIndex).padStart(2, "0")}.png`;

  // Badge màu theo vị trí layer
  const badges = [
    { bg: "#fef9c3", color: "#854d0e", text: "bottom" },
    { bg: "#dcfce7", color: "#166534", text: "mid-low" },
    { bg: "#dbeafe", color: "#1e40af", text: "mid" },
    { bg: "#ede9fe", color: "#5b21b6", text: "mid-high" },
    { bg: "#fce7f3", color: "#9d174d", text: "top" },
  ];
  const badge = badges[Math.min(index, badges.length - 1)];

  const card = document.createElement("div");
  card.className = "layer-card";
  card.id = `card-${cardIndex}`;

  card.innerHTML = `
    <div class="card-header">
      <span class="name">Layer ${cardIndex}</span>
      <span class="badge" style="background:${badge.bg};color:${badge.color}">${badge.text}</span>
    </div>
    <div class="canvas-wrap" id="wrap-${cardIndex}">
      <div class="loading-overlay" id="loading-${cardIndex}">
        <div class="spinner"></div>
        <span>Đang tải...</span>
      </div>
    </div>
    <div class="card-footer">
      <button class="btn-copy" id="copy-${cardIndex}">📋 Copy</button>
      <button class="btn-dl" id="dl-${cardIndex}">⬇️ PNG</button>
    </div>
  `;

  layersGrid.appendChild(card);

  // Load ảnh
  const img = new Image();
  img.crossOrigin = "anonymous";
  img.onload = () => {
    const wrap = document.getElementById(`wrap-${cardIndex}`);
    const loadingEl = document.getElementById(`loading-${cardIndex}`);
    loadingEl?.remove();
    wrap.appendChild(img);

    // Store canvas ref cho copy
    window[`_layer_img_${cardIndex}`] = img;
  };
  img.onerror = () => {
    const loadingEl = document.getElementById(`loading-${cardIndex}`);
    if (loadingEl) loadingEl.innerHTML = '<span style="color:#f87171">Lỗi tải ảnh</span>';
  };
  img.src = url;
  img.style.maxWidth = "100%";
  img.style.maxHeight = "240px";
  img.style.borderRadius = "4px";

  // Download button
  document.getElementById(`dl-${cardIndex}`).addEventListener("click", () => {
    downloadSingleLayer(url, filename);
  });

  // Copy button
  document.getElementById(`copy-${cardIndex}`).addEventListener("click", async () => {
    const imgEl = window[`_layer_img_${cardIndex}`];
    if (!imgEl) return;

    try {
      // Vẽ lên canvas rồi copy
      const canvas = document.createElement("canvas");
      canvas.width  = imgEl.naturalWidth;
      canvas.height = imgEl.naturalHeight;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(imgEl, 0, 0);

      canvas.toBlob(async (blob) => {
        await navigator.clipboard.write([
          new ClipboardItem({ "image/png": blob })
        ]);
        const btn = document.getElementById(`copy-${cardIndex}`);
        btn.textContent = "✅ Đã copy!";
        setTimeout(() => { btn.textContent = "📋 Copy"; }, 2000);
      }, "image/png");
    } catch {
      alert("Trình duyệt không hỗ trợ copy ảnh. Dùng nút ⬇️ PNG thay thế.");
    }
  });
}

// ── Download All ZIP ──────────────────────────────────────────────────
downloadAllBtn.addEventListener("click", async () => {
  if (!currentLayers.length) return;

  downloadAllBtn.disabled = true;
  downloadAllBtn.textContent = "⏳ Đang tạo ZIP...";
  setProgress(10);

  try {
    await downloadAllAsZip(
      currentLayers,
      originalFilename + "_layers",
      (done, total) => {
        const pct = Math.round((done / total) * 100);
        setProgress(pct);
        log(`Đang đóng gói layer ${done}/${total}...`, "info");
      }
    );
    log("✅ ZIP đã được tải xuống!", "ok");
  } catch (err) {
    log("❌ Lỗi tạo ZIP: " + err.message, "err");
  }

  hideProgress();
  downloadAllBtn.disabled = false;
  downloadAllBtn.textContent = "⬇️ Tải tất cả ZIP";
});

// ── Reset ─────────────────────────────────────────────────────────────
function reset() {
  currentFile = currentBase64 = null;
  currentLayers = [];
  originalFilename = "image";

  autoDetectInput.checked = false;
  updateSliderStates();
  qwenAnalysisPanel.innerHTML = "";
  qwenAnalysisPanel.style.display = "none";

  runBtn.disabled = true;
  downloadAllBtn.disabled = true;
  clearLog();
  hideProgress();
  layersGrid.innerHTML = "";
  resultsSection.style.display = "none";
  previewWrap.style.display = "none";
  previewImg.src = "";
  fileInput.value = "";
  dropIcon.textContent = "📁";
  dropText.textContent = "Kéo thả hoặc click để chọn ảnh";

  // Xóa các img refs
  Object.keys(window).filter(k => k.startsWith("_layer_img_")).forEach(k => delete window[k]);
}

// ── Events ────────────────────────────────────────────────────────────
fileInput.addEventListener("change", (e) => handleFile(e.target.files[0]));
runBtn.addEventListener("click", runPipeline);
resetBtn.addEventListener("click", reset);

dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("drag-over");
});
dropzone.addEventListener("dragleave", () => {
  dropzone.classList.remove("drag-over");
});
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("drag-over");
  handleFile(e.dataTransfer.files[0]);
});
