from __future__ import annotations
import hashlib, io, json
from pathlib import Path
from pypdf import PdfReader
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/'output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_14150_f7b78b7b869e.pdf'
OUT=Path(__file__).resolve().parent/'navigator_00107_certificate_ozon_compact_20261022.pdf'
REPORT=Path(__file__).resolve().parent/'navigator_00107_certificate_ozon_compact_20261022.json'
EXPECTED='f7b78b7b869ebc131519ea8694ee0fa33f2d6afc1c38ec9aedc9963f5778bf8e'
if OUT.exists() or REPORT.exists(): raise RuntimeError('output_exists_inspect_first')
raw=SRC.read_bytes(); src_hash=hashlib.sha256(raw).hexdigest()
if src_hash != EXPECTED: raise RuntimeError('source_hash_mismatch')
r=PdfReader(io.BytesIO(raw))
if len(r.pages)!=11: raise RuntimeError('source_page_count_mismatch')
page_images=[]; sizes=[]
for page in r.pages:
    imgs=page.images
    if len(imgs)!=1: raise RuntimeError('unexpected_source_images_per_page')
    im=Image.open(io.BytesIO(imgs[0].data)).convert('RGB')
    sizes.append(im.size)
    buf=io.BytesIO(); im.save(buf,format='JPEG',quality=92,optimize=True,progressive=False,subsampling=0)
    page_images.append((buf.getvalue(),float(page.mediabox.width),float(page.mediabox.height)))
c=canvas.Canvas(str(OUT),pagesize=(page_images[0][1],page_images[0][2]),pageCompression=1)
for data,w,h in page_images:
    c.setPageSize((w,h));c.drawImage(ImageReader(io.BytesIO(data)),0,0,width=w,height=h,preserveAspectRatio=False,mask=None);c.showPage()
c.save()
rr=PdfReader(str(OUT))
if len(rr.pages)!=11: raise RuntimeError('output_page_count_mismatch')
for i in [0,1,10]:
    imgs=rr.pages[i].images
    if len(imgs)!=1: raise RuntimeError('optimized_image_structure_mismatch')
    p=Path(f'/tmp/nav00107_compact_page{i+1}.jpg');p.write_bytes(imgs[0].data)
report={'created_at_local':'2026-10-22','source_pdf':str(SRC),'source_sha256':src_hash,'source_bytes':len(raw),'optimized_pdf':str(OUT),'optimized_sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'optimized_bytes':OUT.stat().st_size,'source_page_count':len(r.pages),'optimized_page_count':len(rr.pages),'source_image_dimensions':sizes,'jpeg_quality':92,'pixel_content_preserved_except_recompression':True,'page_text_modified':False,'source_file_deleted':False}
REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
