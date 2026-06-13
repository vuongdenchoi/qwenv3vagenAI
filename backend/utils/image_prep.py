from PIL import Image
import base64
import io

def prepare_image(image_bytes: bytes, max_size: int = 1024) -> str:
    """Resize + convert to base64 for Vision API"""
    if not image_bytes:
        raise ValueError("File ảnh bị rỗng (0 bytes).")
        
    try:
        # Đọc ảnh từ bytes bằng Pillow (Hỗ trợ tốt nhất JPG/PNG)
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        
        # Resize nếu quá lớn (tiết kiệm token)
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
        
    except Exception as e:
        raise Exception(f"Không thể đọc file ảnh này. Vui lòng CHỈ SỬ DỤNG file JPG hoặc PNG thông thường thay vì WebP. Chi tiết hệ thống: {e}")

