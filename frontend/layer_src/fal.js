// fal.js — fal.ai Qwen-Image-Layered API integration

const FAL_MODEL = "fal-ai/qwen-image-layered";
const FAL_BASE  = "https://fal.run";

/**
 * Trả về data URI trực tiếp — không upload lên fal.ai storage.
 * fal-ai/qwen-image-layered chấp nhận data URI (base64) trong image_url.
 * Cách này tránh được lỗi CORS khi gọi từ browser localhost.
 */
export async function uploadToFal(base64, mimeType, apiKey) {
  // Trả về data URI thay vì upload lên storage
  return `data:${mimeType};base64,${base64}`;
}

export async function decomposeImage(imageUrl, apiKey, opts = {}, onStatus = null) {
  // Extract base64 and mime type from data URI
  const match = imageUrl.match(/^data:(image\/[a-zA-Z+]+);base64,(.+)$/);
  if (!match) throw new Error("Invalid image format");
  const mime_type = match[1];
  const image_base64 = match[2];

  const payload = {
    image_base64: image_base64,
    mime_type: mime_type,
    api_key: apiKey,
    num_layers: opts.numLayers || 5,
    guidance_scale: opts.guidanceScale || 5,
    num_inference_steps: opts.numInferenceSteps || 30,
    auto_detect: opts.autoDetect || false
  };

  onStatus?.(opts.autoDetect ? "🔍 Qwen3-VL đang phân tích cấu trúc ảnh để tối ưu tham số..." : "Gửi yêu cầu tới backend WillaAI...");

  const resp = await fetch("/extract-layers", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });

  if (!resp.ok) {
    const errText = await resp.text();
    throw new Error(`Lỗi từ backend: ${errText}`);
  }

  const result = await resp.json();
  return result;
}
