"""Shared, dependency-free presentation for the frame and its owner pages."""

import hashlib
import html
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.responses import HTMLResponse

from .branding import BRAND_MARK, ICON_LINK

NAVIGATION = (
    ("overview", "/manage", "Overview"),
    ("appearance", "/manage/appearance", "Appearance"),
    ("events", "/manage/events", "Special days"),
    ("images", "/manage/images", "Your images"),
    ("artwork", "/manage/artwork", "Artwork library"),
    ("event-art", "/manage/event-art", "Special-day art"),
    ("battery", "/manage/battery", "Device health"),
    ("settings", "/manage/settings", "Settings"),
    ("recovery", "/manage/recovery", "Recovery"),
)


CSS = """
:root{color-scheme:light;--canvas:#f5f4ef;--surface:#fff;--ink:#20362c;
--muted:#617168;--line:#dce2da;--accent:#285c43;--soft:#edf3ed;--danger:#9d362b;
--radius:12px;--shadow:0 3px 18px #203e2a06}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-bottom:120px}body{margin:0;background:var(--canvas);
color:var(--ink);font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
a{color:var(--accent);text-underline-offset:3px}a:hover{text-decoration-thickness:2px}
button,input,select,textarea{font:inherit}
button,a,input,select,textarea,summary{touch-action:manipulation}

:focus-visible{outline:3px solid #397b58;outline-offset:4px}img{max-width:100%;height:auto}
h1,h2,h3,p{margin-top:0}h1,h2{font-family:Georgia,"Times New Roman",serif;font-weight:400;
letter-spacing:-.025em;line-height:1.2}h1{font-size:clamp(28px,3vw,38px);margin-bottom:12px}
h2{font-size:24px;margin-bottom:16px}h3{font-size:16px;line-height:1.4;margin-bottom:12px}
p{margin-bottom:16px}
ul,ol{padding-left:24px}
small,.quiet,.help-text{font-size:13px;
color:var(--muted)}

.skip-link{position:fixed;top:10px;left:12px;transform:translateY(-180%);z-index:20;
background:var(--ink);
color:white;
padding:10px 18px;
border-radius:8px}
.skip-link:focus{transform:none}

.brand{display:flex;align-items:center;gap:8px;text-decoration:none;color:var(--ink);
font-family:Georgia,"Times New Roman",serif;font-size:25px;letter-spacing:-.03em;min-height:44px}
.brand img{width:36px;height:36px;margin:0!important;border-radius:10px}
.sidebar{position:fixed;inset:0 auto 0 0;width:230px;padding:28px 20px;display:flex;
flex-direction:column;border-right:1px solid var(--line);background:#203c30;overflow-y:auto;
color:#f7f6ef}
.sidebar .brand{margin:0 8px 30px;color:#f7f6ef}
.nav-caption{text-transform:uppercase;letter-spacing:.12em;
font-size:10px;
color:var(--muted);
font-weight:700;
margin:0 12px 10px}
.owner-nav{display:grid;
gap:4px}

.owner-nav a{display:flex;align-items:center;min-height:44px;padding:10px 12px;border-radius:9px;
text-decoration:none;
color:var(--muted);
font-weight:500}
.owner-nav a:hover{background:#f0f3ec;
color:var(--ink)}

.owner-nav a[aria-current=page]{color:var(--accent);background:#e8efe5;font-weight:650}
.sidebar-foot{margin-top:auto;padding:30px 12px 0}.sidebar-foot a{display:block;min-height:44px}
.sidebar-foot p{font-size:12px;color:var(--muted);margin:6px 0}.owner-content{margin-left:230px}
main{max-width:1320px;margin:0 auto;padding:44px clamp(20px,4vw,56px) 64px;min-width:0}
.page-header{margin-bottom:30px}
.page-description{color:var(--muted);
max-width:740px;
font-size:16px;
margin-bottom:0}

.mobile-header{display:none}
.site-header{max-width:1320px;
margin:auto;
padding:22px clamp(20px,4vw,56px);

display:flex;
justify-content:space-between;
align-items:center;
gap:20px;
border-bottom:1px solid var(--line)}

.site-nav{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.site-nav a{min-height:44px;
display:inline-flex;align-items:center;padding:8px 14px;text-decoration:none;border-radius:9px}
.site-nav a[aria-current=page]{background:var(--soft);
font-weight:650}
.site-nav .manage-link{color:var(--muted);
font-size:13px}

.site-footer{padding:24px clamp(20px,4vw,56px);max-width:1320px;margin:auto;color:var(--muted);
font-size:12px;display:flex;justify-content:space-between;gap:16px;border-top:1px solid var(--line)}
.login main{max-width:580px;
padding-top:60px}
.login .page-header{text-align:center}
.login .site-header{justify-content:center}

section,.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
padding:24px;margin-bottom:20px;box-shadow:var(--shadow);min-width:0}section section,.card section{
box-shadow:none;
padding:20px;
background:#fcfdfa}
section>:last-child,.card>:last-child{margin-bottom:0}

.section-heading{display:flex;
gap:16px;
justify-content:space-between;
align-items:start;
margin-bottom:20px}

.section-heading h2{margin-bottom:6px}.card-grid,.metric-grid,.grid,.fields{display:grid;gap:20px;
grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr))}
.card-grid>.card,.metric-grid>.card,.metric-grid>.metric{margin-bottom:0}
.metric-grid{margin-bottom:24px;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr))}

.metric{padding:22px 24px;
background:var(--surface);
border:1px solid var(--line);
border-radius:var(--radius)}

.metric-label{display:block;color:var(--muted);font-size:13px;margin-bottom:8px}
.metric-value,.metric strong{font-size:27px;line-height:1.25;font-weight:600;display:block}
.metric .battery-status{font-size:18px}
.device-health-grid .metric strong{font-size:22px}
.device-health-grid .metric p{font-size:13px;overflow-wrap:break-word}
.metric strong{overflow-wrap:anywhere}
.metric p{margin:8px 0 0;
font-size:13px;
color:var(--muted)}
.split,.current-next{display:grid;

grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:24px;align-items:start}
.toolbar,.actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:18px 0}
.toolbar label{flex:1 1 170px;margin:0}
.toolbar h2:first-child,.toolbar p:first-child{margin-right:auto}
.toolbar h2,.toolbar p{margin-bottom:0}
.button,button,input[type=submit]{display:inline-flex;align-items:center;justify-content:center;
min-height:44px;padding:10px 18px;border:1px solid var(--accent);border-radius:9px;
background:var(--accent);
color:white;
text-decoration:none;
font-weight:600;
line-height:1.45;
cursor:pointer}

.button:hover,button:hover{background:#204d37;color:white}.button.secondary,button.secondary{
color:var(--accent);
background:var(--surface);
border-color:#b6c8b9}
.button.secondary:hover,button.secondary:hover{background:var(--soft)}

.button.danger,button.danger{color:var(--danger);background:#fff6f3;border-color:#e8b9b1}
.button.danger:hover,button.danger:hover{background:#fbe8e3}
button:disabled{opacity:.5;
cursor:not-allowed}

form{margin:0}label{display:block;font-weight:550;margin:16px 0 8px;overflow-wrap:anywhere}
label:first-child{margin-top:0}
label .quiet,label small{font-weight:400;
display:block;
margin-top:5px}

input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=submit]),select,textarea{
display:block;width:100%;max-width:100%;min-height:44px;padding:10px 12px;background:#fff;
border:1px solid #7b8a80;border-radius:8px;color:var(--ink);margin-top:6px}
input[type=file]{padding:8px!important;font-size:14px}input::file-selector-button{padding:6px 10px;
border:1px solid var(--line);
border-radius:5px;
background:var(--soft);
color:var(--ink);
margin-right:10px}

input[type=checkbox],input[type=radio]{width:20px;height:20px;accent-color:var(--accent);
vertical-align:middle;
margin:0 10px 2px 0;
flex-shrink:0}
label:has(input[type=checkbox]),label:has(input[type=radio]){
min-height:44px;font-weight:400;line-height:1.5;padding:8px 0}label br{display:none}
textarea{resize:vertical;
min-height:110px}
fieldset{min-width:0;
padding:20px;
border:1px solid var(--line);

border-radius:10px;
margin:22px 0}
legend{padding:0 8px;
font-weight:600}
form .grid,form .fields{align-items:start}

.fields label,.grid label{margin-top:0}
.sticky-actions{position:sticky;
bottom:0;
background:#fffffff2;

backdrop-filter:blur(8px);
border-top:1px solid var(--line);
padding:16px 0;
margin-top:24px;
display:flex;

gap:12px;align-items:center;flex-wrap:wrap;z-index:2}
.notice{padding:16px 20px;border-radius:10px;border:1px solid #c8dbcc;background:var(--soft);
margin-bottom:24px;
color:#2d503b}
.notice p:last-child{margin-bottom:0}
.error,.notice.error{color:var(--danger)}

.notice.error{background:#fff2ee;
border-color:#e4bdb4}
.notice.success{background:#edf6ec;
border-color:#c7dbc2}

.pill,.status-tag{display:inline-flex;
gap:6px;
align-items:center;
padding:4px 10px;
border-radius:100px;

background:var(--soft);
color:#36543d;
font-size:12px;
font-weight:600;
line-height:1.5;
white-space:normal}

.pill.warning,.status-tag.warning{background:#fbf0d8;color:#76531c}.pill.error,.status-tag.error{
background:#fcebe6;color:var(--danger)}.empty-state{text-align:center;padding:44px 24px;
background:#fafbf7;border:1px dashed #bfccbe;border-radius:12px;margin-bottom:24px}
.empty-state h2{font-size:25px}.empty-state p{color:var(--muted);max-width:540px;margin:0 auto 20px}
.preview,.frame-preview{display:block;
width:100%;
max-width:800px;
aspect-ratio:5/3;
object-fit:contain;

background:#fafbf8;border:1px solid var(--line);border-radius:10px}.preview-wrap{padding:10px;
background:#f3f4ee;border:1px solid var(--line);border-radius:14px}.gallery img,.card-grid img{
width:100%;aspect-ratio:5/3;object-fit:contain;border-radius:9px;background:#f5f6f0}
.library-card{padding:18px;display:flex;flex-direction:column}.library-card .artwork-thumb{
aspect-ratio:4/3;object-fit:contain}.library-card h2{font-size:22px;margin:16px 0 8px}
.library-card details{font-size:13px;margin-bottom:0}.library-card summary{padding:10px 12px}
.variant{padding:12px 0;border-top:1px solid var(--line)}.variant:first-child{border-top:0}
figure{margin:0}.frame-preview:has(figcaption){aspect-ratio:auto;max-width:none;padding:12px;background:white}.frame-preview>img{display:block;width:100%;border-radius:6px}.public-library-invite{margin-top:24px}.eyebrow{text-transform:uppercase;letter-spacing:.15em;font-size:11px;color:var(--muted)}
figcaption{font-size:13px;
color:var(--muted);
margin-top:10px}
.art-title{margin:16px 0 6px}

details{border:1px solid var(--line);border-radius:10px;margin:16px 0;background:#fbfcf9}
summary{cursor:pointer;min-height:44px;padding:14px 18px;font-weight:600;overflow-wrap:anywhere}
details[open]>summary{border-bottom:1px solid var(--line);margin-bottom:16px}
details> :not(summary){margin-left:18px;margin-right:18px}details> :last-child{margin-bottom:18px}
details p{color:var(--muted)}dl{margin:0}dt{font-size:13px;color:var(--muted)}dd{margin:4px 0 18px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:12px;text-align:left;
border-bottom:1px solid var(--line);overflow-wrap:anywhere}th{font-weight:600;color:var(--muted)}
.table-wrap{overflow-x:auto}
code{font-size:.88em;
background:#f0f3ec;
border-radius:4px;
padding:2px 5px;

overflow-wrap:anywhere}
pre{white-space:pre-wrap;
overflow-wrap:anywhere;
background:#f0f3ec;
padding:18px;
border-radius:10px}

hr{border:0;border-top:1px solid var(--line);margin:24px 0}.danger-zone{border-color:#e2bbb3}
@media(min-width:1440px){main{padding-top:54px}}
@media(max-width:1000px){.split,.current-next{grid-template-columns:1fr}.sidebar{width:210px}
.owner-content{margin-left:210px}main{padding:32px 24px 48px}}
@media(max-width:760px){.sidebar{display:none}
.owner-content{margin-left:0}
.mobile-header{display:block;

background:#fbfcf8;border-bottom:1px solid var(--line);padding:14px 20px}.mobile-top{display:flex;
justify-content:space-between;align-items:center;gap:16px}.mobile-top .quiet{font-size:12px}
.mobile-header details{margin:12px 0 0;background:white}.mobile-header summary{padding:10px 12px}
.mobile-header .owner-nav{grid-template-columns:repeat(2,minmax(0,1fr));padding-bottom:8px;gap:2px}
.mobile-header details[open]>summary{margin-bottom:8px}.owner-nav a{font-size:14px;padding:10px}
.toolbar label{flex-basis:100%}main{padding:28px 20px 40px}
.page-header{margin-bottom:24px}
section,.card{padding:22px;
margin-bottom:20px}

.site-header{padding:16px 20px;
flex-wrap:wrap;
gap:8px}
.site-nav{gap:2px}
.site-nav a{padding:8px 10px}

.brand{font-size:23px}.site-footer{padding:22px 20px}.card-grid,.metric-grid,.grid,.fields{gap:16px}
.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
.metric{padding:18px}
.metric-value,.metric strong{font-size:23px}

.section-heading{flex-wrap:wrap}h2{font-size:24px}.login main{padding-top:36px}}
@media(max-width:400px){main{padding-left:16px;padding-right:16px}section,.card{padding:18px}
.metric-grid{grid-template-columns:1fr}
.site-header .site-nav{width:100%}
.site-nav .manage-link{margin-left:auto}

.toolbar .button,.actions .button{flex:1 1 auto}.site-footer{flex-wrap:wrap}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}

.sidebar :focus-visible{outline-color:#e5eee2}
.sidebar .nav-caption{color:#c0cec3;margin-top:22px;font-size:11px}
.sidebar .owner-nav a{color:#dce5dc}
.sidebar .owner-nav a:hover{background:#315141;color:#fff}
.sidebar .owner-nav a[aria-current=page]{background:#e5eee2;color:#203c30}
.sidebar-foot a{color:#e5eee2}.sidebar-foot p{color:#c0cec3}
.section-heading .quiet{margin-bottom:0}
.frame-status{display:flex;gap:12px 24px;flex-wrap:wrap;border-bottom:1px solid var(--line);
padding-bottom:18px;margin-bottom:22px;font-size:14px;color:var(--muted)}
.frame-status strong{font-weight:600;color:var(--ink)}
.current-next figure img{width:100%;height:auto;display:block}
.current-next h3{display:flex;gap:10px;align-items:center}
.current-next .quiet{margin-top:8px}
.card .card{box-shadow:none}
.event-editor{padding:0;background:var(--surface);box-shadow:none}
.event-editor>summary{display:flex;align-items:center;justify-content:space-between;gap:12px}
.event-editor summary .quiet{font-weight:400;text-align:right}
.event-editor form{margin-bottom:18px}
.event-editor summary{font-size:15px}
.form-error{border-left:4px solid var(--danger);padding:14px 18px;background:#fff2ee;
color:#8c2e26;border-radius:6px;margin:12px 0;scroll-margin-top:24px}
.form-error:focus{outline:3px solid var(--danger);outline-offset:3px}
button[aria-busy=true]{cursor:wait;opacity:.8}
.field-help{font-weight:400;font-size:13px;color:var(--muted)}
.preview-result{max-width:900px}
.public .frame-preview{max-width:1040px;border-radius:14px;padding:12px;background:#fff}
.public .public-library-invite{display:flex;align-items:center;justify-content:space-between;
gap:20px;flex-wrap:wrap;background:transparent;border:0;box-shadow:none;padding:24px 0}
.public-library-invite h2{margin-bottom:8px}
.mobile-header .nav-caption{margin:14px 12px 4px;grid-column:1/-1}
.mobile-header .owner-nav{padding-bottom:4px}
input,select,textarea{scroll-margin-top:24px;scroll-margin-bottom:120px}
.table-wrap{max-width:100%}.table-wrap:focus-visible{outline-offset:2px}
caption{text-align:left;color:var(--muted);padding:0 12px 12px;font-size:13px}
@media(max-width:760px){.sticky-actions{padding:12px 0}.event-editor>summary{align-items:start}
.current-next{gap:22px}.public .public-library-invite{align-items:start}
.mobile-top{min-width:0}.mobile-top .brand{min-width:0}.frame-status{gap:8px 18px}}
@media(forced-colors:active){button,.button,input,select,textarea{border:1px solid ButtonText}
.owner-nav a[aria-current=page]{outline:2px solid Highlight}}
"""


# A small progressive enhancement preserves native HTML forms without a framework.
JAVASCRIPT = r"""
(() => {
  document.querySelectorAll('[data-weather-options]').forEach(group => {
    const toggle = group.closest('form').querySelector('[name="weather"]');
    if (!toggle) return;
    const update = () => { group.hidden = !toggle.checked; };
    toggle.addEventListener('change', update); update();
  });
  document.querySelectorAll('[data-species-choice]').forEach(button => {
    button.addEventListener('click', () => {
      button.closest('form').querySelectorAll('input[name^="species_"][type="checkbox"]')
        .forEach(input => { input.checked = button.dataset.speciesChoice === 'all'; });
    });
  });
  document.addEventListener('submit', async event => {
    const form = event.target;
    if (form.method.toLowerCase() !== 'post' || form.target ||
        /\/(login|logout|password|provision)$/.test(new URL(form.action).pathname)) return;
    event.preventDefault();
    if (form.dataset.busy) return;
    const submitter = event.submitter;
    if (submitter?.classList.contains('danger') &&
        !window.confirm('Confirm: ' + submitter.textContent.trim() + '?')) return;
    const data = new FormData(form);
    if (submitter?.name) data.append(submitter.name, submitter.value);
    form.querySelector('.form-error')?.remove();
    form.dataset.busy = 'true';
    const original = submitter?.textContent;
    if (submitter) {
      submitter.disabled = true; submitter.setAttribute('aria-busy', 'true');
      submitter.textContent = /prepare|preview/i.test(original) ? 'Preparing artwork…' : 'Saving…';
    }
    const announceError = message => {
      const box = document.createElement('p'); box.className = 'form-error';
      box.setAttribute('role', 'alert'); box.tabIndex = -1; box.textContent = message;
      form.prepend(box); box.focus();
    };
    try {
      const response = await fetch(form.action, {
        method: 'POST', credentials: 'same-origin', headers: {'Accept': 'text/html'},
        body: form.enctype === 'multipart/form-data' ? data : new URLSearchParams(data)
      });
      if (response.status === 401 || new URL(response.url).pathname === '/manage/login') {
        announceError('Your session has expired. Your entries are still here. ' +
          'Sign in in another tab and check the current state before retrying.');
        const link = document.createElement('a'); link.href = '/manage/login';
        link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Sign in';
        form.querySelector('.form-error').append(' ', link); return;
      }
      if (!response.ok) {
        const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
        announceError(doc.querySelector('[data-request-error]')?.textContent ||
          'This change could not be confirmed. Your entries are still here. ' +
          'Check the current state.');
        return;
      }
      window.location.assign(response.url);
    } catch {
      announceError('The connection was interrupted. Your entries are still here. ' +
        'Reconnect and review the current state before retrying.');
    } finally {
      delete form.dataset.busy;
      if (submitter) {
        submitter.disabled = false; submitter.removeAttribute('aria-busy');
        submitter.textContent = original;
      }
    }
  });
})();
"""
ASSET_VERSION = hashlib.sha256((CSS + JAVASCRIPT).encode()).hexdigest()[:12]


def local_time(value):
    """One readable timestamp convention for frame locations in this POC."""
    if not value:
        return "Not reported"
    return (
        datetime.fromisoformat(value)
        .astimezone(ZoneInfo("America/Denver"))
        .strftime("%b %-d, %-I:%M %p %Z")
    )


def _navigation(active):
    groups = (
        ("Your frame", NAVIGATION[:3]),
        ("Collection", NAVIGATION[3:6]),
        ("Setup & health", NAVIGATION[6:]),
    )
    sections = []
    for label, items in groups:
        links = []
        for key, url, text in items:
            current = ' aria-current="page"' if key == active else ""
            links.append(f'<a href="{url}"{current}>{text}</a>')
        sections.append('<p class="nav-caption">' + label + "</p>" + "".join(links))
    return '<nav class="owner-nav" aria-label="Frame management">' + "".join(sections) + "</nav>"


def page(title, body, *, active=None, public=False, description=None):
    """Render trusted caller HTML inside an accessible shared page shell.

    Callers must escape interpolated user values in ``body``. Title and description
    are escaped here. ``active='login'`` deliberately omits owner navigation.
    """
    escape = html.escape
    login = active == "login"
    brand = '<a class="brand" href="/" aria-label="Emviary home">' + BRAND_MARK + "Emviary</a>"
    if public or login:
        navigation = (
            ""
            if login
            else (
                '<nav class="site-nav" aria-label="Main navigation">'
                + '<a href="/"'
                + (' aria-current="page"' if active == "frame" else "")
                + ">Frame</a>"
                + '<a href="/library"'
                + (' aria-current="page"' if active == "artwork" else "")
                + ">Artwork</a>"
                + '<a class="manage-link" href="/manage">Manage</a></nav>'
            )
        )
        shell = '<header class="site-header">' + brand + navigation + "</header>"
        wrapper_class = "login" if login else "public"
    else:
        navigation = _navigation(active)
        shell = (
            '<aside class="sidebar">'
            + brand
            + ""
            + navigation
            + '<div class="sidebar-foot"><a href="/">View your frame</a><p>A '
            "little nature, every day.</p></div></aside>"
            + '<header class="mobile-header"><div class="mobile-top">'
            + brand
            + '<a class="quiet" href="/">View '
            "frame</a></div><details><summary>Menu · "
            + escape(next((label for key, _, label in NAVIGATION if key == active), "Manage"))
            + "</summary>"
            + navigation
            + "</details></header>"
        )
        wrapper_class = "owner-content"
    heading = '<div class="page-header"><h1>' + escape(str(title)) + "</h1>"
    if description:
        heading += '<p class="page-description">' + escape(str(description)) + "</p>"
    heading += "</div>"
    if "<h1" in body:
        heading = ""
    footer = (
        '<footer class="site-footer"><span>Emviary &middot; A little nature, every day.</span>'
        + ('<a href="/manage">Manage your frame</a>' if public else '<a href="/">View frame</a>')
        + "</footer>"
    )
    document_title = str(title) + " · Emviary" if title != "Emviary" else "Emviary"
    return HTMLResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>'
        + escape(document_title)
        + "</title>"
        + ICON_LINK
        + f'<link rel="stylesheet" href="/assets/{ASSET_VERSION}/ui.css">'
        + f'<script src="/assets/{ASSET_VERSION}/ui.js" defer></script></head><body>'
        + '<a class="skip-link" href="#main-content">Skip to content</a>'
        + shell
        + '<div class="'
        + wrapper_class
        + '"><main id="main-content" tabindex="-1">'
        + heading
        + body
        + "</main>"
        + footer
        + "</div></body></html>",
        headers={
            "Cache-Control": "no-store",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; img-src 'self'; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'",
        },
    )
