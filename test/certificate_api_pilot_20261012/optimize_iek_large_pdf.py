"""Create a visually faithful upload copy of the oversized official scanned IEK PDF."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

BASE = Path(__file__).resolve().parent
SHA = "1a59bd9fc5915b112dbeb18e7608cfeb28c0e719650a9ad172777319760580a4"
SOURCE = BASE / "iek_new_docs" / f"{SHA}.pdf"
RENDER = BASE / "iek_new_docs_pdf_render"
OUT_DIR = BASE / "iek_new_docs_compressed"
JPG_DIR = OUT_DIR / "raster"
OUTPUT = OUT_DIR / f"{SHA}_200dpi_q95.pdf"
AUDIT = BASE / "iek_large_pdf_optimization_audit.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    if not SOURCE.is_file() or sha256(SOURCE) != SHA:
        raise RuntimeError("Official source PDF is missing or no longer matches its URL hash")
    OUT_DIR.mkdir(exist_ok=True)
    JPG_DIR.mkdir(exist_ok=True)
    reader = PdfReader(str(SOURCE))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        source_image = RENDER / f"{SHA}-{i}.png"
        if not source_image.is_file():
            raise RuntimeError(f"Original page render is missing: {source_image.name}")
        image = Image.open(source_image).convert("RGB")
        jpg = JPG_DIR / f"{SHA}-{i}.jpg"
        image.save(jpg, format="JPEG", quality=95, subsampling=0, optimize=True, progressive=True)
        pages.append((page.mediabox.width, page.mediabox.height, jpg, image.size))

    out = canvas.Canvas(str(OUTPUT), pagesize=(pages[0][0], pages[0][1]), pageCompression=1)
    out.setTitle("Official IEK declaration upload copy")
    out.setAuthor("IEK official source PDF; raster-preserving-size encoding for marketplace transport")
    for width, height, jpg, pixels in pages:
        out.setPageSize((width, height))
        out.drawImage(ImageReader(str(jpg)), 0, 0, width=width, height=height, preserveAspectRatio=False)
        out.showPage()
    out.save()

    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(SOURCE), "source_sha256": sha256(SOURCE), "source_bytes": SOURCE.stat().st_size,
        "output": str(OUTPUT), "output_sha256": sha256(OUTPUT), "output_bytes": OUTPUT.stat().st_size,
        "page_count": len(pages), "render_dpi": 200, "jpeg_quality": 95,
        "jpeg_subsampling": 0, "pages": [{"page": i, "pixels": list(pixels), "jpeg_bytes": jpg.stat().st_size}
                                         for i, (_, _, jpg, pixels) in enumerate(pages, start=1)],
        "content_note": "Each page was rendered from the official source at 200 dpi and encoded as a high-quality JPEG; no text, page, or annotation was added or removed.",
    }
    AUDIT.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({"source_bytes": result["source_bytes"], "output_bytes": result["output_bytes"],
                      "pages": result["page_count"], "sha256": result["output_sha256"],
                      "audit": str(AUDIT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
