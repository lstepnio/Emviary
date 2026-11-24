"""A small public showcase of the approved, owner-editable occasion collection."""

import hashlib
import json
from html import escape
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from .showcase import framed_image

ROOT = Path(__file__).with_name("special_day_gallery_assets")
CATALOG = json.loads((ROOT / "catalog.json").read_text())
VERSION = hashlib.sha256((ROOT / "catalog.json").read_bytes()).hexdigest()[:12]
FILES = {item["filename"] for item in CATALOG}

GALLERY_CSS = """
.occasion-header{max-width:760px;margin:24px 0 32px}
.occasion-header h1{margin-bottom:16px}.occasion-header p{color:var(--muted);font-size:18px}
.occasion-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:30px 24px}
.occasion-card{min-width:0;text-align:center}
.occasion-open{display:block;width:100%;padding:0;border:0;background:transparent;
color:inherit;line-height:0;border-radius:8px}
.occasion-open:hover{background:#eeeae0}.occasion-card h2{font-size:19px;margin:12px 0 0}
.occasion-invite{margin:36px auto;padding:28px;background:#eee9df;border-radius:14px}
.occasion-invite-top{display:flex;justify-content:space-between;align-items:center;gap:24px}
.occasion-invite h2{margin:0 0 8px}.occasion-invite p{margin:0;color:var(--muted)}
.occasion-invite .occasion-grid{margin-top:18px}.occasion-invite .occasion-card h2{display:none}
.occasion-dialog{width:min(940px,calc(100vw - 24px));max-height:92dvh;overflow:auto;
padding:24px;border:1px solid var(--line);border-radius:14px;
background:var(--canvas);color:var(--ink)}
.occasion-dialog::backdrop{background:#142c22b8}
.occasion-dialog-top{display:flex;justify-content:space-between;gap:20px;align-items:start}
.occasion-dialog-top h2{font-size:28px;margin:0}
.occasion-dialog img{display:block;width:100%;height:auto;
margin:20px 0;border-radius:6px}.occasion-dialog p{margin:8px 0;color:var(--muted)}
.occasion-dialog .finished-frame{margin:20px auto}
.occasion-dialog .finished-frame img{margin:0;border-radius:0}
.occasion-dialog-nav{display:flex;gap:10px;justify-content:space-between;margin-top:20px}
@media(max-width:900px){.occasion-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:600px){.occasion-grid{grid-template-columns:1fr;gap:28px}
.occasion-invite{padding:20px}.occasion-invite-top{display:block}
.occasion-invite-top .button{margin-top:18px}
.occasion-invite .occasion-grid{grid-template-columns:1fr}
.occasion-invite .occasion-card:not(:first-child){display:none}.occasion-dialog{padding:18px}}
"""

GALLERY_JAVASCRIPT = r"""
(() => {
 const root=document.querySelector('[data-special-gallery]');if(!root)return;
 const items=JSON.parse(root.dataset.catalog), dialog=root.querySelector('dialog');let index=0;
 function fill(){const item=items[index];
  dialog.querySelector('[data-occasion-title]').textContent=item.label;
  const img=dialog.querySelector('img');img.src=item.url;img.alt=item.heading+' '+item.message;
  dialog.querySelector('[data-occasion-copy]').textContent=item.heading+' '+item.message;}
 root.querySelectorAll('[data-special-open]').forEach(button=>button.addEventListener('click',()=>{
  index=items.findIndex(i=>i.slug===button.dataset.specialOpen);fill();dialog.showModal();}));
 dialog.querySelector('[data-occasion-close]').addEventListener('click',()=>dialog.close());
 dialog.querySelector('[data-occasion-previous]').addEventListener('click',()=>{
  index=(index+items.length-1)%items.length;fill();});
 dialog.querySelector('[data-occasion-next]').addEventListener('click',()=>{
  index=(index+1)%items.length;fill();});
})();
"""


def image_url(item):
    return f"/special-day-media/{VERSION}/{item['filename']}"


def card(item, index=0):
    picture = framed_image(image_url(item), item["heading"] + " " + item["message"])
    if index > 2:
        picture = picture.replace("<img ", '<img loading="lazy" ')
    return (
        '<article class="occasion-card"><button class="occasion-open" data-special-open="'
        + escape(item["slug"], quote=True)
        + '" aria-label="View '
        + escape(item["label"], quote=True)
        + '">'
        + picture
        + "</button><h2>"
        + escape(item["label"])
        + "</h2></article>"
    )


def homepage_invite():
    chosen = [
        next(x for x in CATALOG if x["slug"] == slug) for slug in ("valentine", "summer", "autumn")
    ]
    return (
        '<section class="occasion-invite"><div class="occasion-invite-top"><div>'
        "<h2>A little more personal.</h2><p>Seasonal nature and a little affectionate snark.</p>"
        '</div><a class="button secondary" href="/special-days">Explore special days</a></div>'
        '<div class="occasion-grid">'
        + "".join(
            '<div class="occasion-card">' + framed_image(image_url(x), x["heading"]) + "</div>"
            for x in chosen
        )
        + "</div></section>"
    )


def markup():
    data = [{**item, "url": image_url(item)} for item in CATALOG]
    return (
        '<header class="occasion-header"><p class="eyebrow">Special days</p>'
        "<h1>Special days, your way.</h1><p>Seasonal nature. Personal words. "
        'A little affectionate snark.</p></header><section data-special-gallery data-catalog="'
        + escape(json.dumps(data), quote=True)
        + '"><div class="occasion-grid">'
        + "".join(card(item, n) for n, item in enumerate(CATALOG))
        + '</div><dialog class="occasion-dialog" aria-labelledby="occasion-detail-title">'
        '<div class="occasion-dialog-top"><h2 id="occasion-detail-title" data-occasion-title></h2>'
        '<button type="button" class="secondary" data-occasion-close>Close</button></div>'
        '<div class="finished-frame"><img class="finished-frame__art" width="800" '
        'height="480" alt=""><img class="finished-frame__surround" width="1536" '
        'height="1024" src="/showcase-media/20261123/07-frame-overlay.webp" alt=""></div>'
        "<p data-occasion-copy></p>"
        '<div class="occasion-dialog-nav"><button type="button" class="secondary" '
        'data-occasion-previous>Previous</button><button type="button" class="secondary" '
        "data-occasion-next>Next</button></div></dialog></section>"
    )


def install_routes(app):
    @app.get("/special-days")
    def special_day_collection():
        from .ui import page

        return page(
            "Special days",
            markup(),
            active="special-days",
            public=True,
            description="Distinct nature art and affectionate words for the days that matter.",
        )

    @app.get("/special-day-media/{version}/{filename}")
    def special_day_media(version: str, filename: str):
        if version != VERSION or filename not in FILES:
            raise HTTPException(404, "Artwork unavailable")
        return FileResponse(
            ROOT / filename,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
            },
        )
