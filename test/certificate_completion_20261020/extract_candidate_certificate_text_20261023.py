#!/usr/bin/env python3
"""Extract searchable text from fresh uncovered-source candidate PDFs."""
from __future__ import annotations

from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().with_name("candidate_certificate_text_20261023.txt")
SOURCES = {
    "Arlight declaration 52132/25": "output_to_user/certificates/group_1/documents/arlight/94D46BAFE361664EA7621A1A4A70FD33.pdf",
    "Arlight certificate 0123651": "output_to_user/certificates/group_1/documents/arlight/8D4F02314DBE404FA8A115C777042CE4.pdf",
    "Arlight certificate 0333370": "output_to_user/certificates/group_1/documents/arlight/B93165BC4283E449AF1E139B53863098.pdf",
    "IN HOME declaration 60403/26": "output_to_user/certificates/group_2/IN_HOME/documents/2af3c6d70766_D4AD85E8BEBDCE783525AB54A97FAFC6.pdf",
}


def main() -> None:
    blocks = []
    for label, relative in SOURCES.items():
        path = ROOT / relative
        if not path.is_file():
            blocks.append(f"## {label}\nMISSING: {path}\n")
            continue
        reader = PdfReader(str(path))
        blocks.append(f"## {label}\nFILE: {path}\nPAGES: {len(reader.pages)}\n")
        for number, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            blocks.append(f"--- PAGE {number} ---\n{text}\n")
    OUT.write_text("\n".join(blocks), encoding="utf-8")
    print(f"extracted {len(SOURCES)} PDFs to {OUT}")


if __name__ == "__main__":
    main()
