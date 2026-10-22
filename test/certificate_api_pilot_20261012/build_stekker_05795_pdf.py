"""Build a one-page A4 Ozon transport copy; preserve the official JPEG source."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "output_to_user/certificates/group_1/documents/stekker/960606eb9021386ae1d5e24c.jpg"
OUT_DIR = Path(__file__).resolve().parent / "stekker_05795_upload_files"
OUTPUT = OUT_DIR / "05795_22.pdf"
AUDIT = OUT_DIR / "05795_22_pdf_audit.json"
EXPECTED_SOURCE_SHA256 = "57a0c318989769d7f98cd66177269ec2d84b71fa7575f682d3b5dc0a62b7c608"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    if not SOURCE.is_file() or SOURCE.is_symlink() or sha256(SOURCE) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("Original supplier scan is missing or its SHA-256 changed")
    OUT_DIR.mkdir(exist_ok=True)
    with Image.open(SOURCE) as image:
        pixels = image.size
    page_width, page_height = A4
    scale = min(page_width / pixels[0], page_height / pixels[1])
    draw_width, draw_height = pixels[0] * scale, pixels[1] * scale
    x, y = (page_width - draw_width) / 2, (page_height - draw_height) / 2
    pdf = canvas.Canvas(str(OUTPUT), pagesize=A4, pageCompression=1)
    pdf.drawImage(ImageReader(str(SOURCE)), x, y, width=draw_width, height=draw_height,
                  preserveAspectRatio=False, mask="auto")
    pdf.showPage()
    pdf.save()
    audit = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": str(SOURCE), "source_sha256": sha256(SOURCE),
        "source_bytes": SOURCE.stat().st_size, "source_pixels": list(pixels),
        "output_file": str(OUTPUT), "output_sha256": sha256(OUTPUT),
        "output_bytes": OUTPUT.stat().st_size, "page_count": 1,
        "page_size_points": [round(page_width, 2), round(page_height, 2)],
        "source_was_not_modified": True,
        "content_note": "One raster-preserving A4 page derived from the unchanged official supplier scan; no text or page content added or removed.",
    }
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(OUTPUT), "source_sha256": audit["source_sha256"],
                      "pdf_sha256": audit["output_sha256"], "bytes": audit["output_bytes"],
                      "page_count": audit["page_count"], "source_pixels": pixels}, ensure_ascii=False))


if __name__ == "__main__":
    main()
