"""A public, printable guide for a preconfigured gift, with no device data."""

from .ui import page


def install_routes(app):
    @app.get("/guide")
    def recipient_guide():
        return page(
            "Using your frame",
            '<article class="recipient-guide">'
            '<header class="page-header"><p class="eyebrow">Your Emviary frame</p>'
            "<h1>A little nature, every day.</h1>"
            "<p>Your frame is set up for you. No app, account or subscription is needed "
            "for everyday use.</p></header>"
            '<div class="guide-actions"><button type="button" data-print-guide>'
            "Print this guide</button></div>"
            '<section class="card"><h2>Make yourself at home</h2>'
            "<p>Place the frame indoors, within reach of your home Wi-Fi. Keep its "
            "power switch on. A new picture is scheduled overnight.</p>"
            "<p>The picture stays visible while the frame sleeps. When it changes, "
            "brief flashing is normal. Allow about 30 seconds for a refresh to finish.</p>"
            "</section>"
            '<section class="card"><h2>Three simple controls</h2>'
            '<dl class="guide-controls"><div><dt>Left white button</dt>'
            "<dd>A short press goes to the previous picture.</dd></div>"
            "<div><dt>Right white button</dt><dd>A short press goes to the next picture. "
            "Press once, then wait for the refresh to finish.</dd></div>"
            "<div><dt>Green button</dt><dd>A short press wakes a sleeping frame "
            "to retry Wi-Fi. It also returns from the status screen.</dd></div></dl>"
            "</section>"
            '<section class="card"><h2>Charging and saved pictures</h2>'
            "<p>Use the supplied USB-C cable and tested 5 V USB power adapter. "
            "You can leave the frame plugged in or use it on battery.</p>"
            "<p>If Wi-Fi is unavailable, saved pictures can still rotate. Weather is "
            "removed from those offline pictures. If there is no saved alternative, "
            "the frame keeps its current picture.</p>"
            "<p>A picture can remain visible even when the battery is empty. "
            "If the buttons do not respond, connect the charger and check that the "
            "power switch is on.</p></section>"
            '<section class="card"><h2>Need a hand?</h2>'
            "<p>If charging and a short green-button press do not restore updates, "
            "contact the person who gave you the frame. They handle setup and maintenance. "
            "Let them know if your Wi-Fi name or password changes.</p>"
            "<p>To show the frame status, hold the left white button for five seconds. "
            "A photo of that screen helps your maintainer troubleshoot. "
            "Briefly press green to return to the picture.</p>"
            '<p class="quiet">Keep this guide with your charging cable. Online guide: '
            "emviary.majjix.com/guide</p></section></article>",
            active="guide",
            public=True,
            description="Everyday controls, charging and help for your preconfigured gift.",
        )
