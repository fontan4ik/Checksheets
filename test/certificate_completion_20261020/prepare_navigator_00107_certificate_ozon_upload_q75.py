from __future__ import annotations
import hashlib, io, json
from pathlib import Path
from pypdf import PdfReader
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/'output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_14150_f7b78b7b869e.pdf'
OUT=Path(__file__).resolve().parent/'navigator_00107_certificate_ozon_upload_q75_20261022.pdf'
REPORT=Path(__file__).resolve().parent/'navigator_00107_certificate_ozon_upload_q75_20261022.json'
EXPECTED='f7b78b7b869ebc131519ea8694ee0fa33f2d6afc1c38ec9aedc9963f5778bf8e'
if OUT.exists() or REPORT.exists(): raise RuntimeError('output_exists_inspect_first')
source=SRC.read_bytes(); source_hash=hashlib.sha256(source).hexdigest()
if source_hash!=EXPECTED: raise RuntimeError('source_hash_mismatch')
r=PdfReader(io.BytesIO(source))
if len(r.pages)!=11: raise RuntimeError('source_page_count_mismatch')
images=[];info=[]
for p in r.pages:
    if len(p.images)!=1: raise RuntimeError('unexpected_source_images_per_page')
    im=Image.open(io.BytesIO(p.images[0].data)).convert('RGB')
    im=im.resize((1400,1980),Image.Resampling.LANCZOS)
    buf=io.BytesIO();im.save(buf,format='JPEG',quality=75,optimize=True,progressive=False,subsampling=2)
    images.append(Image.open(io.BytesIO(buf.getvalue())).convert('RGB'))
    info.append({'upload_dimensions_px':[1400,1980],'jpeg_bytes':len(buf.getvalue())})
resolution=1400/(595.08/72)
images[0].save(OUT,format='PDF',save_all=True,append_images=images[1:],resolution=resolution,quality=75,optimize=True)
rr=PdfReader(str(OUT))
if len(rr.pages)!=11: raise RuntimeError('upload_page_count_mismatch')
if any(abs(float(p.mediabox.width)-595.08)>0.2 or abs(float(p.mediabox.height)-841.68)>0.2 for p in rr.pages): raise RuntimeError('upload_page_dimensions_changed')
if OUT.stat().st_size>=10_000_000: raise RuntimeError('still_exceeds_ozon_10mb_file_limit')
manifest={'source_pdf':str(SRC),'source_sha256':source_hash,'source_bytes':len(source),'upload_pdf':str(OUT),'upload_sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'upload_bytes':OUT.stat().st_size,'source_pages':11,'upload_pages':len(rr.pages),'page_size_points':[float(rr.pages[0].mediabox.width),float(rr.pages[0].mediabox.height)],'page_images':info,'content_changes':'image recompression/downsampling only; page sequence, all 11 pages, all text/images, and physical A4 page size preserved','ozon_file_limit_bytes':10_000_000,'under_ozon_file_limit':True,'source_pdf_deleted':False}
REPORT.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
for idx in (0,1,7,10): Path(f'/tmp/nav00107_q75_page{idx+1}.jpg').write_bytes(rr.pages[idx].images[0].data)
print(json.dumps(manifest,ensure_ascii=False,indent=2))
