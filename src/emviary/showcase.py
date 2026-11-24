"""Finished-frame presentation, with independent live artwork and static media."""

from html import escape
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

MEDIA_VERSION = "20261123"
MEDIA_ROOT = Path(__file__).with_name("showcase_assets")
MEDIA_URL = f"/showcase-media/{MEDIA_VERSION}"
REPOSITORY = "https://github.com/lstepnio/Emviary"

PHOTOS = (
    (
        "01-studio-front",
        "Studio portrait",
        "Straight-on view of the finished wood frame",
        1254,
        1254,
    ),
    (
        "02-studio-angle",
        "A different angle",
        "Clark’s Nutcracker in an angled frame on a warm studio backdrop",
        1672,
        941,
    ),
    (
        "03-lifestyle-console",
        "At home",
        "Kingfisher, hawk and sparrow in the finished frame on an oak console",
        1672,
        941,
    ),
    (
        "04-craft-detail",
        "In the details",
        "Distressed wood grain, miter joint and white bezel",
        1672,
        941,
    ),
    (
        "05-lifestyle-portrait",
        "A quiet corner",
        "Mountain Bluebird and Black-capped Chickadee in a vertical interior portrait",
        941,
        1672,
    ),
    (
        "06-current-transparent",
        "Just the frame",
        "Frame with crow and mallard, without a background",
        1312,
        1199,
    ),
    (
        "07-frame-overlay",
        "A frame for every composition",
        "Wood frame surround with an open display area",
        1536,
        1024,
    ),
    (
        "08-dark-studio",
        "After the light settles",
        "Great Horned Owl in the finished frame in a dark studio",
        1672,
        941,
    ),
)
FILMS = (
    ("emviary-showcase-1080p", "The finished frame", "08-dark-studio", "21 seconds", False),
    ("emviary-portrait-1080p", "A moment at home", "05-lifestyle-portrait", "10 seconds", True),
    ("emviary-dark-loop-1080p", "Dark studio", "08-dark-studio", "8-second loop", False),
    ("emviary-studio-loop-1080p", "Warm studio", "02-studio-angle", "8-second loop", False),
)
ANIMATIONS = (
    ("emviary-dark-loop", "Dark studio animation", "08-dark-studio"),
    ("emviary-studio-loop", "Warm studio animation", "02-studio-angle"),
)
MEDIA_TYPES = {
    **{name + ".webp": "image/webp" for name, *_ in PHOTOS},
    **{name + ".mp4": "video/mp4" for name, *_ in FILMS},
    **{name + ".gif": "image/gif" for name, *_ in ANIMATIONS},
    "showcase.js": "text/javascript",
}

SHOWCASE_CSS = """
.finished-frame{position:relative;aspect-ratio:3/2;width:100%;max-width:1040px;
margin-inline:auto;isolation:isolate}
.finished-frame img{display:block;border:0;border-radius:0;background:transparent;margin:0}
.finished-frame .finished-frame__art{position:absolute;left:21.2%;top:21.1%;
width:57.6%;height:51.8%;object-fit:fill;z-index:0}
.finished-frame .finished-frame__surround{position:relative;width:100%;height:auto;
pointer-events:none;z-index:1}
.public .frame-preview.finished-preview{border:0;background:transparent;padding:0}
.finished-preview figcaption{max-width:760px;margin:8px auto 28px;text-align:center}
.delivered-slot .finished-frame{margin-block:-12px 4px}
.frame-showcase-invite{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);
gap:clamp(24px,4vw,52px);align-items:center;padding:0;overflow:hidden;background:#eee9df}
.frame-showcase-invite>img{width:100%;height:100%;min-height:240px;object-fit:cover}
.frame-showcase-invite>div{padding:24px 32px 24px 0}
.frame-showcase-invite p{max-width:430px}
.battery-highlight{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.5fr);
gap:24px 48px;padding:32px;margin-top:32px;border:1px solid #cbd5c7;
border-radius:14px;background:#eaf0e5;scroll-margin-top:24px}
.battery-highlight h2{font-size:clamp(28px,4vw,42px);line-height:1.12;margin:8px 0 12px}
.battery-highlight p{max-width:650px;margin:8px 0}
.battery-highlight dl{display:flex;flex-wrap:wrap;gap:16px 32px;margin:0 0 20px}
.battery-highlight dt{color:var(--muted);font-size:13px}
.battery-highlight dd{font-size:28px;font-weight:600;margin:0}
.battery-highlight .battery-date{font-size:13px}
.showcase-header{padding-block:12px 20px;max-width:760px}
.showcase-header h1{font-size:clamp(36px,6vw,64px);line-height:1.07;max-width:680px}
.showcase-header .page-description{max-width:620px}
.showcase-jump-links{display:flex;flex-wrap:wrap;gap:8px 16px;margin:24px 0 0}
.showcase-jump-links a{display:inline-flex;align-items:center;min-height:44px}
.showcase-lead img{display:block;width:100%;height:auto;border-radius:14px}
.showcase-section{margin:48px 0 0;padding:32px 0 0;background:transparent;border:0;
border-top:1px solid var(--line);border-radius:0;box-shadow:none;scroll-margin-top:20px}
.showcase-section>p{max-width:720px}
.showcase-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:32px 24px}
.showcase-photo img{display:block;width:100%;height:auto;border-radius:10px}
.showcase-photo--portrait{grid-column:1/-1;max-width:520px;width:100%;margin-inline:auto}
@media(max-width:760px){.frame-showcase-invite{grid-template-columns:1fr;gap:0}
.battery-highlight{grid-template-columns:1fr;padding:24px;gap:16px}
.frame-showcase-invite>div{padding:24px}.frame-showcase-invite>img{min-height:0}
.showcase-grid{grid-template-columns:1fr;gap:28px}.showcase-section{margin-top:32px}
.showcase-header h1{font-size:38px}
.finished-preview figcaption{text-align:left}}
.showcase-lead{overflow:hidden;border-radius:14px}
.showcase-lead:hover img{animation-play-state:paused}
@media(prefers-reduced-motion:no-preference){
.showcase-lead img{animation:showcase-drift 18s ease-in-out infinite alternate}
@keyframes showcase-drift{from{transform:scale(1)}to{transform:scale(1.018)}}}
@media(prefers-reduced-motion:reduce){.showcase-jump-links{scroll-behavior:auto}}
"""


def framed_image(src, alt):
    """Keep current artwork in its own image, independent of the decorative surround."""
    return (
        '<div class="finished-frame"><img class="finished-frame__art" width="800" '
        'height="480" src="'
        + escape(src, quote=True)
        + '" alt="'
        + escape(alt, quote=True)
        + '"><img class="finished-frame__surround" width="1536" height="1024" '
        'src="' + MEDIA_URL + '/07-frame-overlay.webp" alt="" aria-hidden="true"></div>'
    )


def showcase_invite():
    return (
        '<section class="frame-showcase-invite" aria-labelledby="finished-frame-title">'
        '<img src="' + MEDIA_URL + '/03-lifestyle-console.webp" loading="lazy" '
        'width="1672" height="941" alt="The finished Emviary frame on an oak console">'
        '<div><p class="eyebrow">The finished frame</p><h2 id="finished-frame-title">'
        'Made to feel at home.</h2><p class="quiet">A closer look at the wood, the artwork, '
        "and the frame that brings it together.</p><p><strong>Early battery data points to "
        "over a year between charges.</strong> "
        '<a href="/showcase#battery">See the measurements and projection</a>.</p>'
        '<a class="button secondary" '
        'href="/showcase">Explore the finished frame</a></div></section>'
    )


def battery_highlight():
    """A dated, deliberately qualified observation, independent of live owner telemetry."""
    return (
        '<section class="battery-highlight" id="battery" aria-labelledby="battery-heading">'
        '<div><p class="eyebrow">Early battery results</p>'
        '<h2 id="battery-heading">Over a year.<br>At the observed rate.</h2>'
        '<p class="battery-date">Measured through November 23, 2026</p></div><div>'
        "<dl><div><dt>Battery remaining</dt><dd>92%</dd></div>"
        "<div><dt>Days observed unplugged</dt><dd>41.1</dd></div>"
        "<div><dt>Percentage points used</dt><dd>6</dd></div></dl>"
        "<p>The unplugged trend projects more than a year to the 20% recharge threshold. "
        "That is based on 42 daily readings, with reported charge moving from 98% to 92%.</p>"
        '<p class="quiet">This is an early straight-line projection with limited confidence, '
        "not a completed year-long endurance test. Battery discharge, temperature and use "
        "can change the result.</p><p><strong>The picture stays.</strong> "
        "The last picture stays visible when the battery runs out. "
        "If Wi-Fi drops, the frame keeps cycling through saved pictures while it has power.</p>"
        '<a href="'
        + REPOSITORY
        + '/blob/main/docs/BATTERY_RESULTS.md">Read the battery evidence and method</a>'
        "</div></section>"
    )


def photo_markup(photo):
    name, _, alt, width, height = photo
    modifier = " showcase-photo--portrait" if name.startswith("05") else ""
    return (
        '<figure class="showcase-photo' + modifier + '"><img loading="lazy" '
        'decoding="async" width="'
        + str(width)
        + '" height="'
        + str(height)
        + '" src="'
        + MEDIA_URL
        + "/"
        + name
        + '.webp" alt="'
        + escape(alt, quote=True)
        + '"></figure>'
    )


def showcase_markup():
    return (
        '<header class="showcase-header"><p class="eyebrow">Emviary / The finished frame</p>'
        "<h1>A little nature.<br>A place in your home.</h1>"
        '<p class="page-description">Distressed wood, a quiet paper-like display, and artwork '
        "with room to breathe. Explore the finished frame from every angle.</p>"
        '<nav class="showcase-jump-links" aria-label="Showcase sections">'
        '<a href="#battery">Battery results</a><a href="#photographs">Photographs</a>'
        '</nav></header><figure class="showcase-lead"><img width="1672" height="941" '
        'fetchpriority="high" src="' + MEDIA_URL + '/08-dark-studio.webp" '
        'alt="Finished Emviary frame with Great Horned Owl artwork in a dark studio">'
        "</figure>"
        + battery_highlight()
        + '<section class="showcase-section" id="photographs"><h2>The frame, in focus.</h2>'
        '<div class="showcase-grid">'
        + "".join(photo_markup(p) for p in PHOTOS[:5])
        + "</div></section>"
    )


def install_routes(app):
    @app.get("/showcase")
    def showcase():
        from .ui import page

        return page(
            "The finished frame",
            showcase_markup(),
            active="showcase",
            public=True,
            description="The finished Emviary frame, photographs and early battery results.",
        )

    @app.get("/showcase-media/{version}/{filename}")
    def showcase_media(version: str, filename: str):
        if version != MEDIA_VERSION or filename not in MEDIA_TYPES:
            raise HTTPException(404, "Showcase asset unavailable")
        path = MEDIA_ROOT / filename
        if not path.is_file():
            raise HTTPException(404, "Showcase asset unavailable")
        return FileResponse(
            path,
            media_type=MEDIA_TYPES[filename],
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
            },
        )
