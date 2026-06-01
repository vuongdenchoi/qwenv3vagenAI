// zipper.js — Tạo file ZIP chứa tất cả layer PNG

/**
 * Load JSZip từ CDN (lazy load khi cần)
 */
let _JSZip = null;

async function loadJSZip() {
  if (_JSZip) return _JSZip;

  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js";
    script.onload = () => { _JSZip = window.JSZip; resolve(window.JSZip); };
    script.onerror = () => reject(new Error("Không load được JSZip"));
    document.head.appendChild(script);
  });
}

/**
 * Fetch URL và trả về ArrayBuffer
 */
async function fetchArrayBuffer(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Fetch failed: ${url} (${resp.status})`);
  return resp.arrayBuffer();
}

/**
 * Tạo và download ZIP chứa tất cả layer
 * @param {Array} layers  - [{ url, index, label }]
 * @param {string} prefix - tên prefix file (vd: "image_layers")
 * @param {Function} onProgress - callback(current, total)
 */
export async function downloadAllAsZip(layers, prefix = "qwen_layers", onProgress = null) {
  const JSZip = await loadJSZip();
  const zip = new JSZip();

  const folder = zip.folder(prefix);

  for (let i = 0; i < layers.length; i++) {
    const layer = layers[i];
    onProgress?.(i, layers.length);

    try {
      const buffer = await fetchArrayBuffer(layer.url);
      const filename = `layer_${String(i + 1).padStart(2, "0")}.png`;
      folder.file(filename, buffer);
    } catch (e) {
      console.warn(`Bỏ qua layer ${i + 1}:`, e.message);
    }
  }

  onProgress?.(layers.length, layers.length);

  // Generate ZIP
  const blob = await zip.generateAsync({
    type: "blob",
    compression: "DEFLATE",
    compressionOptions: { level: 6 }
  });

  // Trigger download
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${prefix}_${Date.now()}.zip`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

/**
 * Download một layer đơn lẻ
 */
export async function downloadSingleLayer(url, filename) {
  try {
    const buffer = await fetchArrayBuffer(url);
    const blob = new Blob([buffer], { type: "image/png" });
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(blobUrl), 5000);
  } catch {
    // Fallback: mở URL trực tiếp
    window.open(url, "_blank");
  }
}
