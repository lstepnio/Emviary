"""A public, printable guide with no private device data."""

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from .ui import page

GUIDE_ASSETS = Path(__file__).with_name("guide_assets")

GUIDE_HTML = """
<article class="recipient-guide">
<header class="page-header"><p class="eyebrow">Using your Emviary frame</p>
<h1>Switch it on.<br>Make yourself at home.</h1>
<p>Switch the frame on and give your first picture about 30 seconds to appear.
It is already saved on the frame, even if Wi-Fi is unavailable.</p>
<p>Leave the power on for a new picture overnight. No app or subscription is needed.</p>
</header>
<nav class="guide-actions" aria-label="In this guide">
<a href="#buttons">Buttons</a><a href="#status">Frame status</a>
<a href="#management">Manage your frame</a><a href="#power">Power &amp; charging</a>
<button type="button" class="secondary" data-print-guide>Print guide</button></nav>
<section class="card" id="buttons"><p class="eyebrow">Everyday controls</p>
<h2>Press once. Let the picture change.</h2>
<p>The screen flashes as it refreshes. That is normal. Give it about 30 seconds.</p>
<figure class="guide-hardware">
<img src="/guide-media/rear-buttons.webp" width="1536" height="1024" loading="lazy"
alt="Rear controls, with one green wake button followed by two white picture buttons">
<figcaption>From the back, left to right: green, previous, next.</figcaption>
</figure>
<dl class="guide-controls">
<div><dt>Left white button</dt><dd>Tap for the previous picture.</dd></div>
<div><dt>Right white button</dt><dd>Tap for the next picture. With gift mode off,
this also requests artwork queued on the management website.
If the gift welcome is on screen, this opens the gift.</dd></div>
<div><dt>Green button</dt><dd>Wake the frame to reconnect to Wi-Fi and open its
local controls. Also returns from the status screen.</dd></div>
<div><dt>Hold the left white button</dt><dd>Hold for <strong>5 seconds</strong>
to show the frame status.</dd></div></dl>
<p class="quiet guide-note">On USB power, a green wake also checks for new artwork.
On battery, use the right white button to request the next picture.</p></section>
<section class="card" id="status"><p class="eyebrow">A quick check</p>
<h2>See what the frame is doing.</h2>
<ol class="guide-steps"><li>Hold the <strong>left white button for 5 seconds</strong>
until the <strong>Your frame</strong> screen appears.</li>
<li>Check the battery, Wi-Fi, last refresh and next scheduled wake.
The IP address helps you open the frame's local controls.</li>
<li>Tap <strong>green</strong> to return to your picture.</li></ol>
<p>Need help? Send a photo of this screen. Its QR code opens Emviary;
choose <strong>Manage</strong> to visit the management website.</p></section>
<section class="card" id="management"><p class="eyebrow">Two useful places</p>
<h2>Art online. Wi-Fi on the frame.</h2>
<div class="guide-management">
<div><h3>The management website</h3>
<p>Choose artwork, edit Special Days and messages, change the daily schedule,
and check battery and connection history.</p>
<p><a class="button" href="/manage">Open management</a></p>
<p>At home, sign-in can be automatic when home-network access is enabled.
Elsewhere, choose <strong>Sign in with Authentik</strong> and use your approved account.
The owner password is also available.</p></div>
<div><h3>The frame's local controls</h3>
<p>Use these to manage the frame's saved Wi-Fi networks, check the device,
or troubleshoot its connection.</p>
<ol class="guide-steps"><li>Connect USB power and tap <strong>green</strong> to wake it.
USB keeps it awake while you work.</li>
<li>Connect your phone or computer to the <strong>same Wi-Fi</strong> as the frame.</li>
<li>Open <a href="http://emviary.local">emviary.local</a> in your browser.
If that does not open, try <a href="http://photoframe.local">photoframe.local</a>
or the IP address on the status screen.</li></ol>
<p>If asked, enter the frame's local password. This is separate from the website sign-in.</p>
</div></div></section>
<section class="card" id="power"><p class="eyebrow">Power &amp; charging</p>
<h2>Charge it. Or leave it plugged in.</h2>
<figure class="guide-hardware">
<img src="/guide-media/rear-ports.webp" width="1448" height="1086" loading="lazy"
alt="Side of the rear housing showing the SD card slot, power switch and USB-C port">
<figcaption>Left to right in this view: SD card slot, power switch, USB-C.</figcaption>
</figure>
<dl class="guide-controls">
<div><dt>USB-C port</dt><dd>Use a standard USB-C cable and a USB power adapter
(5 V, 1 A or more). Charge it and unplug, or leave it plugged in.</dd></div>
<div><dt>Power switch</dt><dd>Leave it <strong>ON</strong> for normal use.
The frame sleeps automatically. To turn it fully off, unplug USB-C and set the switch to OFF.
The picture stays visible.</dd></div>
<div><dt>SD card slot</dt><dd>Leave it empty. Emviary stores its saved pictures
inside the frame and does not use an SD card.</dd></div>
</dl></section>
<section class="card"><h2>If a picture stops changing</h2>
<p>Check that the power switch is ON and connect USB power.
If the frame is showing ordinary artwork, tap the right white button.
If charging does not start, try another cable or USB charger.</p>
<p>The last picture stays visible when the battery runs out. If Wi-Fi drops,
the frame keeps cycling through saved pictures while it has power.</p>
<p>If your Wi-Fi has changed, open <a href="/manage/recovery">Recovery</a> on the management
website for help reconnecting. A photo of the frame status is useful if you need a hand.</p>
</section></article>
"""


def install_routes(app):
    @app.get("/guide-media/{filename}")
    def guide_media(filename: str):
        if filename not in {"rear-buttons.webp", "rear-ports.webp"}:
            raise HTTPException(404, "Guide image unavailable")
        return FileResponse(
            GUIDE_ASSETS / filename,
            media_type="image/webp",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/guide")
    def recipient_guide():
        return page(
            "Using your frame",
            GUIDE_HTML,
            active="guide",
            public=True,
            description="Buttons, frame status, management, Wi-Fi and USB-C charging.",
        )
