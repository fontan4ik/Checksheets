from __future__ import annotations
import hashlib, io, json, math
from pathlib import Path
from pypdf import PdfReader
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/'output_to_user/certificates/group_2/NAVIGATOR/documents/NAV_eac_certificate_14150_f7b78b7b869e.pdf'
OUT=Path(__file__).resolve().parent/'navigator_00107_certificate_ozon_upload_20261022.pdf'
REPORT=Path(__file__).resolve().parent/'navigator_00107_certificate_ozon_upload_20261022.json'
EXPECTED='f7b78b7b869ebc131519ea8694ee0fa33f2d6afc1c38ec9aedc9963f5778bf8e'
if OUT.exists() or REPORT.exists(): raise RuntimeError('output_exists_inspect_first')
source=SRC.read_bytes();source_hash=hashlib.sha256(source).hexdigest()
if source_hash!=EXPECTED: raise RuntimeError('source_hash_mismatch')
reader=PdfReader(io.BytesIO(source))
if len(reader.pages)!=11: raise RuntimeError('source_page_count_mismatch')
processed=[]; dimensions=[]
for page in reader.pages:
    imgs=page.images
    if len(imgs)!=1: raise RuntimeError('unexpected_source_images_per_page')
    im=Image.open(io.BytesIO(imgs[0].data)).convert('RGB')
    original=im.size; target=(1500,2122)
    im=im.resize(target,Image.Resampling.LANCZOS)
    buf=io.BytesIO(); im.save(buf,format='JPEG',quality=80,optimize=True,progressive=False,subsampling=2)
    processed.append(Image.open(io.BytesIO(buf.getvalue())).convert('RGB'))
    dimensions.append({'source_pixels':original,'upload_pixels':target,'jpeg_bytes':len(buf.getvalue())})
# 1500x2122 at 181.5 dpi preserves the original A4 page box.
processed[0].save(OUT,format='PDF',save_all=True,append_images=processed[1:],resolution=181.5,quality=80,optimize=True)
result=PdfReader(str(OUT))
if len(result.pages)!=11: raise RuntimeError('upload_page_count_mismatch')
if any(abs(float(p.mediabox.width)-595.08)>0.2 or abs(float(p.mediabox.height)-841.68)>0.2 for p in result.pages): raise RuntimeError('upload_page_dimensions_changed')
base64_bytes=4*((OUT.stat().st_size+2)//3)
manifest={'source_pdf':str(SRC),'source_sha256':source_hash,'source_bytes':len(source),'upload_pdf':str(OUT),'upload_sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'upload_bytes':OUT.stat().st_size,'source_pages':11,'upload_pages':len(result.pages),'page_size_points':[float(result.pages[0].mediabox.width),float(result.pages[0].mediabox.height)],'upload_image_dimensions':dimensions,'jpeg_quality':80,'resampled_from_1653x2338_to_1500x2122':True,'content_changes':'image recompression/downsampling only; pages/text/order/physical page size preserved','base64_bytes_without_json_metadata':base64_bytes,'estimated_api_request_bytes_with_12kb_metadata':base64_bytes+12000,'below_existing_15mb_payload_guard':base64_bytes+12000<15_000_000,'source_pdf_deleted':False}
REPORT.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
for idx in (0,1,7,10):
 Path(f'/tmp/nav00107_upload_page{idx+1}.jpg').write_bytes(result.pages[idx].images[0].data)
print(json.dumps(manifest,ensure_ascii=False,indent=2))
