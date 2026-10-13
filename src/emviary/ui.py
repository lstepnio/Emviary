"""Shared, dependency-free presentation for the frame and its owner pages."""

import hashlib
import html
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi.responses import HTMLResponse

from .branding import BRAND_MARK, ICON_LINK
from .event_ui import EVENT_CSS

NAVIGATION = (
    ("overview", "/manage", "Overview"),
    ("appearance", "/manage/appearance", "Appearance"),
    ("events", "/manage/events", "Special days"),
    ("artwork", "/manage/artwork", "Artwork library"),
    ("battery", "/manage/battery", "Device health"),
    ("settings", "/manage/settings", "Settings"),
    ("recovery", "/manage/recovery", "Recovery"),
)


CSS = """
:root{color-scheme:light;--canvas:#f5f4ef;--surface:#fff;--ink:#20362c;
--muted:#617168;--line:#dce2da;--accent:#285c43;--soft:#edf3ed;--danger:#9d362b;
--radius:12px;--shadow:0 3px 18px #203e2a06}
*{box-sizing:border-box}
html{scroll-behavior:smooth;
scroll-padding-bottom:120px}
body{margin:0;
background:var(--canvas);

color:var(--ink);font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
a{color:var(--accent);text-underline-offset:3px}a:hover{text-decoration-thickness:2px}
button,input,select,textarea{font:inherit}
[hidden]{display:none!important}
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
.refresh-slots{grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:24px}
.refresh-slots .delivered-slot{grid-row:span 2}
.prepared-slot{padding:16px;border:1px solid var(--line);border-radius:10px;background:#fafbf8}
.frame-context{font-size:13px;color:var(--muted);margin:-10px 0 24px}
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
figure{margin:0}
.frame-preview:has(figcaption){aspect-ratio:auto;
max-width:none;
padding:12px;
background:white}
.frame-preview>img{display:block;
width:100%;
border-radius:6px}
.public-library-invite{margin-top:24px}
.eyebrow{text-transform:uppercase;
letter-spacing:.15em;
font-size:11px;
color:var(--muted)}

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
.refresh-slots .delivered-slot{grid-row:auto}
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
.artwork-grid{gap:16px;align-items:start}
.card.artwork-card{padding:14px;box-shadow:none}
.artwork-card:has(.artwork-select input:checked){border-color:var(--accent);background:#f4f8f2}
.artwork-card h2{font-size:20px;line-height:1.25;margin:14px 0 6px}
.artwork-card>.pill{align-self:start;font-size:11px;padding:2px 8px;margin:6px 0}
.artwork-card .artwork-media{border-radius:8px;overflow:hidden;background:#f5f6f0}
.artwork-card .artwork-media a{display:block}
.artwork-card .artwork-thumb{display:block;aspect-ratio:4/3}
.artwork-card .artwork-heading{margin:14px 0 6px;display:flex;flex-wrap:wrap;
align-items:center;gap:8px}
.artwork-card .artwork-heading h2{font-size:20px;line-height:1.25;margin:0;flex:1 1 100%}
.artwork-card .artwork-heading .pill{padding:2px 8px;font-size:11px}
.artwork-card .artwork-meta{font-size:12px;color:var(--muted);margin:0 0 8px}
.artwork-actions{display:flex;justify-content:space-between;align-items:center;
gap:10px;flex-wrap:wrap}
.artwork-actions .artwork-select{margin:0;padding:8px 0;font-size:13px;min-height:44px}
.artwork-actions input[type=checkbox]{width:18px;height:18px;margin-right:6px}
.artwork-card .compact-action{font-size:13px;padding:8px 10px;min-height:44px}
.artwork-actions .compact-action{background:transparent;border:0;padding-right:0;
padding-left:0;text-decoration:underline;text-underline-offset:3px}
.special-day-art{margin-top:24px}.special-day-art>.card-grid{margin-top:24px}
.collection-filter-options{flex:1 1 100%;margin:0}
.collection-filter-options .fields{grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}
#artwork-bulk{border-top:1px solid var(--line);padding:12px 0;margin:12px 0 16px}
#artwork-bulk .quiet{margin:0 0 6px}
#artwork-bulk button{font-size:13px;padding:8px 12px}
#artwork-bulk [data-selection-count]{font-size:13px;color:var(--muted)}
.library-help{margin-top:24px}
.variant-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
@media(max-width:760px){#artwork-library .toolbar>label{flex:1 1 120px}
#artwork-library .toolbar>label:first-child{flex-basis:100%}}
@media(max-width:1000px){.sticky-actions{position:static;backdrop-filter:none}}
caption{text-align:left;color:var(--muted);padding:0 12px 12px;font-size:13px}
@media(max-width:760px){.sticky-actions{padding:12px 0}.event-editor>summary{align-items:start}
.current-next{gap:22px}.public .public-library-invite{align-items:start}
.mobile-top{min-width:0}.mobile-top .brand{min-width:0}.frame-status{gap:8px 18px}}
@media(forced-colors:active){button,.button,input,select,textarea{border:1px solid ButtonText}
.owner-nav a[aria-current=page]{outline:2px solid Highlight}}
.recovery-steps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;
list-style:none;padding:0;margin:24px 0}
.recovery-steps li{padding:9px;border-radius:8px;background:var(--soft);color:var(--muted);
font-size:13px;text-align:center}
.recovery-steps [aria-current=step]{background:var(--accent);color:white;font-weight:600}
#usb-recovery [data-usb-cloud]{margin-top:24px;padding-top:24px;border-top:1px solid var(--line)}
#usb-recovery progress{width:100%;margin:16px 0 0}
#usb-recovery [data-usb-preview]{max-width:560px;margin-top:16px}

.recovery-heading h2{margin-bottom:8px}.recovery-heading p{color:var(--muted);max-width:650px}
.recovery-steps{background:none;
gap:12px;
margin:26px 0}
.recovery-steps li{display:flex;
align-items:center;
gap:8px;
text-align:left;
background:none;
padding:0;
font-size:12px}

.recovery-steps li span{display:grid;
place-items:center;
flex:0 0 28px;
height:28px;
border-radius:50%;
background:var(--soft)}

.recovery-steps [aria-current=step]{color:var(--ink);
background:none}
.recovery-steps [aria-current=step] span,
.recovery-steps [data-complete=true] span{background:var(--accent);
color:white}

.recovery-stage{display:flex;
align-items:center;
gap:20px;
padding:24px;
border-radius:14px;
background:var(--soft);
margin:24px 0}

.recovery-stage h3{margin:0 0 8px}
.recovery-stage p{margin:0;
color:var(--muted);
max-width:650px;
font-size:14px}

.recovery-orb{display:grid;
place-items:center;
flex:0 0 52px;
height:52px;
background:white;
border-radius:50%;
color:var(--accent);
font-size:28px}

[data-recovery-state=needs_attention] .recovery-stage,
[data-recovery-state=paused] .recovery-stage{background:#fcf0d9}

[data-recovery-state=finished] .recovery-stage{background:#e9f2e5}
.recovery-intro ol{padding-left:20px;line-height:2}.recovery-intro{margin:18px 0}
.recovery-details{margin-top:28px}.recovery-details p{font-size:12px}
@media(max-width:600px){.recovery-stage{padding:18px;
gap:12px}
.recovery-orb{flex-basis:40px;
height:40px}
.recovery-steps{gap:8px}
.recovery-steps li{flex-direction:column;
align-items:flex-start;
font-size:11px}
}


.library-header{margin-bottom:18px}.library-header h1{margin-bottom:8px}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}
section.artwork-library{background:transparent;border:0;box-shadow:none;padding:0}
.library-toolbar{display:flex;align-items:center;gap:12px;margin:0 0 12px}
.library-toolbar label{margin:0}
.library-toolbar>label:not(.library-search){display:flex;
align-items:center;
gap:8px;
font-size:12px;
color:var(--muted)}

.library-search{flex:1}.library-search input{margin:0;max-width:none}
.library-toolbar select{margin:0;
width:auto;
font-size:13px;
min-height:42px;
padding:8px 32px 8px 12px}

.library-filter-menu{position:relative;margin:0;border:0;background:none;padding:0}
.library-filter-menu>summary{padding:10px 15px;
border:1px solid var(--line);
border-radius:10px;
font-size:13px;
white-space:nowrap}

.library-filter-panel{position:absolute;
z-index:8;
right:0;
top:48px;
width:360px;
padding:20px;
background:white;
border:1px solid var(--line);
border-radius:12px;
box-shadow:var(--shadow);
display:grid;
grid-template-columns:1fr 1fr;
gap:16px}

.library-filter-panel select{width:100%;max-width:100%}.library-filter-panel label{font-size:12px}
.library-results{display:flex;
align-items:center;
gap:8px;
flex-wrap:wrap;
font-size:12px;
color:var(--muted);
min-height:30px;
margin-bottom:14px}

.filter-chip{background:var(--soft);
border-radius:18px;
padding:4px 10px;
text-decoration:none;
color:var(--ink)}

#artwork-bulk{position:sticky;
bottom:16px;
z-index:7;
background:white;
border:1px solid var(--line);
border-radius:12px;
box-shadow:var(--shadow);
padding:12px;
display:flex;
align-items:center;
gap:12px;
flex-wrap:wrap}

#artwork-bulk[hidden]{display:none}#artwork-bulk .actions{margin:0}
@media(max-width:760px){#artwork-bulk{left:50%;width:calc(100vw - 32px)}
.library-toolbar{flex-wrap:wrap;
gap:8px}
.library-search{flex:1 1 100%}
.library-toolbar>label:not(.library-search){flex:1}
.library-filter-panel{width:min(360px,calc(100vw - 40px))}
.library-header{margin-bottom:14px}
}

"""

CSS += (
    EVENT_CSS
    + """
.public-compositions{max-width:1000px;margin:36px auto}
.public-compositions figure{margin:0;padding:12px;border:1px solid var(--line);
border-radius:14px;background:var(--surface)}
.public-compositions figcaption{margin-top:8px;color:var(--muted);font-size:14px}
.public-compositions .current-next{margin-top:16px}
"""
)


# A small progressive enhancement preserves native HTML forms without a framework.
JAVASCRIPT = r"""
(() => {
  document.querySelectorAll('[data-weather-options]').forEach(group => {
    const toggle = group.closest('form').querySelector('[name="weather"]');
    if (!toggle) return;
    const update = () => { group.hidden = !toggle.checked; };
    toggle.addEventListener('change', update); update();
  });
  const updateSelection = () => {
    const bulk = document.getElementById('artwork-bulk');
    if (!bulk) return;
    const choices = [...bulk.elements].filter(input => input.type === 'checkbox' &&
      input.name.startsWith('selected_') && !input.disabled);
    const count = choices.filter(input => input.checked).length;
    bulk.hidden = count === 0;
    const output = document.querySelector('[data-selection-count]');
    if (output) output.textContent = count + ' selected';
    const actions = bulk.querySelector('[data-selection-actions]');
    if (actions) actions.hidden = count === 0;
    bulk.querySelectorAll('button[type="submit"], button:not([type])').forEach(button => {
      button.disabled = count === 0;
    });
    const select = document.querySelector('[data-select-page]');
    if (select) {
      select.hidden = false;
      select.textContent = count === choices.length && count > 0 ?
        'Clear selection' : 'Select loaded artwork';
    }
  };
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-select-page]');
    if (!button) return;
    const bulk = document.getElementById('artwork-bulk');
    if (!bulk) return;
    const choices = [...bulk.elements].filter(input => input.type === 'checkbox' &&
      input.name.startsWith('selected_') && !input.disabled);
    const selected = choices.every(input => input.checked);
    choices.forEach(input => { input.checked = !selected; }); updateSelection();
  });
  document.addEventListener('change', updateSelection);
  updateSelection();
  document.addEventListener('input', event => {
    if (event.target.closest('form')) {
      document.querySelectorAll('main > .notice.success').forEach(notice => {
        notice.hidden = true;
      });
    }
    const form = event.target.closest('form[data-appearance-preview]');
    if (!form || event.target.type === 'hidden') return;
    form.querySelector('[name="preview_token"]').value = '';
    form.querySelector('[data-queue-appearance]').disabled = true;
    form.querySelector('[data-appearance-preview-result]').hidden = true;
  });
  const focusId = location.hash.slice(1) || new URLSearchParams(location.search).get('focus');
  if (focusId) {
    const target = document.getElementById(focusId);
    const details = target?.closest('details');
    if (details) {
      details.open = true;
      details.querySelector('summary')?.focus({preventScroll: true});
      target.scrollIntoView({block: 'start'});
    }
  }
  let pendingForm = null;
  let libraryObserver;
  let libraryRequest;
  const readLibrary = async response => {
    const target = new URL(response.url);
    const expectedPath = document.getElementById('artwork-library')?.dataset.libraryPath ||
      '/manage/artwork';
    if (!response.ok || target.origin !== location.origin ||
        target.pathname !== expectedPath) {
      throw new Error('Artwork could not be loaded. Sign in again if needed, then retry.');
    }
    const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
    const section = doc.getElementById('artwork-library');
    if (!section) throw new Error('The artwork response was incomplete. Try again.');
    return section;
  };
  const appendLibraryPage = (current, next) => {
    const seen = new Set([...current.querySelectorAll('[data-artwork-id]')]
      .map(item => item.dataset.artworkId));
    const grid = current.querySelector('.artwork-grid');
    next.querySelectorAll('[data-artwork-id]').forEach(card => {
      if (!seen.has(card.dataset.artworkId)) grid.append(card);
    });
    current.dataset.lastPage = next.dataset.lastPage;
    current.dataset.totalPages = next.dataset.totalPages;
    current.querySelector('[data-artwork-pagination]')?.remove();
    const pagination = next.querySelector('[data-artwork-pagination]');
    if (pagination) current.querySelector('.library-help').before(pagination);
  };
  const initInfiniteLibrary = () => {
    libraryObserver?.disconnect();
    const current = document.getElementById('artwork-library');
    if (!current) return;
    current.querySelector('.library-loader')?.remove();
    const pagination = current.querySelector('[data-artwork-pagination]');
    if (pagination) pagination.hidden = true; // Native pagination remains the no-JS fallback.
    const url = pagination?.querySelector('[data-artwork-next]')?.href;
    const loader = document.createElement('div'); loader.className = 'library-loader';
    const message = document.createElement('p');
    message.className = 'quiet'; message.setAttribute('role', 'status');
    message.setAttribute('aria-live', 'polite');
    const count = current.querySelectorAll('[data-artwork-id]').length;
    message.textContent = count + (url ? ' artworks loaded' :
      ' artworks loaded · End of collection');
    loader.append(message); current.querySelector('.library-help').before(loader);
    if (!url) return;
    const button = document.createElement('button'); button.type = 'button';
    button.className = 'secondary'; button.textContent = 'Load more artwork';
    loader.prepend(button);
    const more = async () => {
      if (libraryRequest || pendingForm || !current.isConnected) return;
      libraryRequest = new AbortController(); const controller = libraryRequest;
      button.disabled = true; message.textContent = 'Loading artwork…';
      try {
        const response = await fetch(url, {credentials: 'same-origin', signal: controller.signal});
        const next = await readLibrary(response);
        if (controller.signal.aborted || !current.isConnected) return;
        appendLibraryPage(current, next); updateSelection(); initInfiniteLibrary();
      } catch (error) {
        if (error.name !== 'AbortError' && current.isConnected) {
          message.textContent = error.message; button.disabled = false;
          libraryObserver?.disconnect(); // Retry is explicit, not an endless failing loop.
        }
      } finally {
        if (libraryRequest === controller) libraryRequest = undefined;
        if (controller.signal.aborted || !current.isConnected) initInfiniteLibrary();
      }
    };
    button.addEventListener('click', more);
    if ('IntersectionObserver' in window) {
      libraryObserver = new IntersectionObserver(entries => {
        if (entries.some(entry => entry.isIntersecting)) more();
      }, {rootMargin: '180px'});
      libraryObserver.observe(loader);
    }
  };
  const refreshLibraryRange = async (response, current) => {
    const initial = await readLibrary(response);
    const url = new URL(response.url);
    const start = Math.min(Number(current.dataset.firstPage), Number(initial.dataset.totalPages));
    const end = Math.min(Number(current.dataset.lastPage), Number(initial.dataset.totalPages));
    let next;
    for (let page = start; page <= end; page++) {
      url.searchParams.set('p', page);
      const part = Number(initial.dataset.firstPage) === page ? initial :
        await readLibrary(await fetch(url, {credentials: 'same-origin'}));
      if (!next) next = part;
      else appendLibraryPage(next, part);
    }
    return next;
  };
  let filterTimer, filterRequest;
  const applyLibraryFilters = async form => {
    filterRequest?.abort(); libraryRequest?.abort();
    const controller = new AbortController(); filterRequest = controller;
    const params = new URLSearchParams(new FormData(form)); params.delete('p');
    const url = new URL(form.action); url.search = params.toString();
    const current = document.getElementById('artwork-library');
    const query = form.querySelector('[name="q"]');
    const typing = document.activeElement === query;
    const selection=[query.selectionStart,query.selectionEnd];
    const menuOpen=form.querySelector('.library-filter-menu').open;
    try {
      current.setAttribute('aria-busy','true');
      const response=await fetch(url,{credentials:'same-origin',signal:controller.signal});
      const next = await readLibrary(response);
      if (controller.signal.aborted ||
          new URLSearchParams(new FormData(form)).toString()!==params.toString()) return;
      current.replaceWith(next); history.replaceState({},'',url);
      next.querySelector('.library-filter-menu').open=menuOpen;
      initLibraryFilters(); updateSelection(); initInfiniteLibrary();
      if (typing) {
        const field = next.querySelector('[name="q"]'); field.focus({preventScroll:true});
        field.setSelectionRange(...selection);
      }
    } catch(error) {
      if (error.name !== 'AbortError') {
        current.querySelector('[data-library-feedback]').textContent = error.message;
      }
    } finally { current.removeAttribute('aria-busy'); }
  };
  const initLibraryFilters = () => {
    const form = document.querySelector('[data-library-filters]');
    if (!form || form.dataset.enhanced) return;
    form.dataset.enhanced='true'; form.querySelector('.library-filter-apply').hidden=true;
    form.addEventListener('submit',event=>{event.preventDefault();applyLibraryFilters(form);});
    form.addEventListener('change',event=>{if(event.target.tagName==='SELECT')applyLibraryFilters(form);});
    form.querySelector('[name="q"]').addEventListener('input',()=>{
      clearTimeout(filterTimer); filterTimer=setTimeout(()=>applyLibraryFilters(form),300);
    });
  };
  document.addEventListener('click',event=>{
    document.querySelectorAll('.library-filter-menu[open]').forEach(menu=>{
      if(!menu.contains(event.target))menu.open=false;
    });
  });
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape')document.querySelectorAll('.library-filter-menu[open]')
      .forEach(menu=>{menu.open=false;});
  });
  initLibraryFilters();
  initInfiniteLibrary();
  document.addEventListener('submit', async event => {
    const form = event.target;
    const action = new URL(form.getAttribute('action') || location.href, location.href);
    if (form.method.toLowerCase() !== 'post' || form.target ||
        /\/(login|logout|password|provision)$/.test(action.pathname)) return;
    event.preventDefault();
    if (pendingForm) return;
    const submitter = event.submitter;
    if (submitter?.classList.contains('danger') &&
        !window.confirm('Confirm: ' + submitter.textContent.trim() + '?')) return;
    const data = new FormData(form);
    if (submitter?.name) data.append(submitter.name, submitter.value);
    form.querySelector('.form-error')?.remove();
    form.querySelectorAll('[data-server-invalid]').forEach(input => {
      input.removeAttribute('aria-invalid'); input.removeAttribute('data-server-invalid');
    });
    libraryRequest?.abort();
    libraryObserver?.disconnect();
    form.dataset.busy = 'true'; form.setAttribute('aria-busy', 'true'); pendingForm = form;
    // Capture values first, then freeze all forms so later edits cannot disappear on redirect.
    const locked = [...new Set([...document.forms].flatMap(item => [...item.elements]))]
      .filter(control => !control.disabled && control.type !== 'hidden');
    locked.forEach(control => { control.disabled = true; });
    const original = submitter?.textContent;
    if (submitter) {
      submitter.disabled = true; submitter.setAttribute('aria-busy', 'true');
      submitter.textContent = /prepare|preview/i.test(original) ? 'Preparing artwork…' : 'Saving…';
    }
    const announceError = (message, fields = []) => {
      const box = document.createElement('p'); box.className = 'form-error';
      box.setAttribute('role', 'alert'); box.tabIndex = -1; box.textContent = message;
      form.prepend(box);
      fields.slice(0, 20).forEach(name => {
        const input = [...form.elements].find(control => control.name === name &&
          control.type !== 'hidden');
        if (!input) return;
        input.setAttribute('aria-invalid', 'true'); input.dataset.serverInvalid = 'true';
        const link = document.createElement('a'); link.href = '#';
        const labelElement = input.labels?.[0] || input.closest('label');
        const label = [...(labelElement?.childNodes || [])]
          .filter(node => node.nodeType === Node.TEXT_NODE)
          .map(node => node.textContent.trim()).filter(Boolean).join(' ') || name;
        link.textContent = 'Check ' + label;
        link.addEventListener('click', e => { e.preventDefault(); input.focus(); });
        box.append(' ', link);
      });
      box.focus();
    };
    const sessionExpired = () => {
      announceError('Your session has expired. Your entries are still here. ' +
        'Sign in in another tab, then retry this change.');
      const link = document.createElement('a'); link.href = '/manage/login';
      link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Sign in';
      form.querySelector('.form-error').append(' ', link);
    };
    try {
      const auth = await fetch('/manage/session', {
        credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'}
      });
      if (auth.status === 401) { sessionExpired(); return; }
      if (!auth.ok) {
        announceError('Sign-in could not be checked. Your entries are still here. Try again.');
        return;
      }
      const current = await auth.json();
      data.set('csrf', current.csrf);
      document.querySelectorAll('form input[name="csrf"]').forEach(input => {
        const destination = new URL(input.form.getAttribute('action') || location.href,
          location.href);
        if (!/\/(login|logout)$/.test(destination.pathname)) {
          input.value = current.csrf;
        }
      });
      const isPreview = submitter?.hasAttribute('data-preview-appearance');
      const response = await fetch(isPreview ? submitter.formAction : action.href, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Accept': isPreview ? 'application/json' : 'text/html'},
        body: form.enctype === 'multipart/form-data' ? data : new URLSearchParams(data)
      });
      if (response.status === 401 || new URL(response.url).pathname === '/manage/login') {
        sessionExpired(); return;
      }
      if (isPreview && response.headers.get('content-type')?.includes('application/json')) {
        const result = await response.json();
        if (!response.ok) {
          announceError(result.message || result.detail?.message ||
            (typeof result.detail === 'string' ? result.detail :
              'The preview could not be prepared.'),
            Object.keys(result.field_errors || {}));
          return;
        }
        form.querySelector('[data-appearance-preview-image]').src = result.preview_url;
        form.querySelector('[name="preview_token"]').value = result.token;
        form.querySelector('[data-appearance-preview-result]').hidden = false;
        form.querySelector('[data-queue-appearance]').disabled = false;
        form.querySelector('[data-appearance-preview-result]').focus();
        return;
      }
      if (!response.ok) {
        const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
        const error = doc.querySelector('[data-request-error]');
        let fields = [];
        try { fields = JSON.parse(error?.dataset.errorFields || '[]'); } catch {}
        announceError(error?.textContent ||
          'This change could not be confirmed. Your entries are still here. ' +
          'Check the current state.', Array.isArray(fields) ? fields : []);
        return;
      }
      if (form.hasAttribute('data-library-action')) {
        const current = document.getElementById('artwork-library');
        const card = form.closest('[data-artwork-id]');
        const cards = [...current.querySelectorAll('[data-artwork-id]')];
        const expanded = cards.filter(item => item.querySelector('.artwork-remove-options')?.open)
          .map(item => item.dataset.artworkId);
        const selected = form.id === 'artwork-bulk' ? [] :
          [...current.querySelectorAll('input[form="artwork-bulk"]:checked')]
            .map(input => input.name);
        const index = cards.indexOf(card);
        const top = (card || form).getBoundingClientRect().top;
        const keys = [card?.dataset.artworkId, cards[index + 1]?.dataset.artworkId,
          cards[index - 1]?.dataset.artworkId];
        let next;
        try { next = await refreshLibraryRange(response, current); }
        catch {
          announceError('Your change was saved, but the library could not reload. ' +
            'Reload this page to see the current collection.');
          return;
        }
        const target = new URL(response.url);
        if (next && target.origin === location.origin && target.pathname === '/manage/artwork') {
          current.replaceWith(next); initLibraryFilters();
          next.querySelectorAll('[data-artwork-id]').forEach(item => {
            const details = item.querySelector('.artwork-remove-options');
            if (details && expanded.includes(item.dataset.artworkId)) details.open = true;
          });
          next.querySelectorAll('input[form="artwork-bulk"]').forEach(input => {
            input.checked = selected.includes(input.name);
          });
          updateSelection();
          target.searchParams.set('p', next.dataset.firstPage);
          history.replaceState(null, '', target.pathname + target.search);
          initInfiniteLibrary();
          const freshCards = [...next.querySelectorAll('[data-artwork-id]')];
          const anchor = keys.map(key => freshCards.find(item => item.dataset.artworkId === key))
            .find(Boolean) || freshCards[0];
          next.querySelector('[data-library-feedback]').textContent =
            (card ? card.querySelector('h2').textContent : '') +
            (form.dataset.libraryMessage ||
              (data.get('exclude') === '1' ? ' excluded from rotation.' :
                ' restored to rotation.'));
          if (!card) {
            window.scrollBy({top: next.querySelector('#artwork-bulk').getBoundingClientRect().top
              - top, behavior: 'instant'});
            next.querySelector('#artwork-bulk button')?.focus({preventScroll: true});
          } else if (anchor) {
            window.scrollBy({top: anchor.getBoundingClientRect().top - top, behavior: 'instant'});
            [...anchor.querySelectorAll('button,a,summary')]
              .find(control => control.getClientRects().length && !control.disabled)
              ?.focus({preventScroll: true});
          } else {
            next.querySelector('input[type="search"]')?.focus({preventScroll: true});
          }
          return;
        }
      }
      window.location.assign(response.url);
    } catch {
      announceError('The connection was interrupted. Your entries are still here. ' +
        'Reconnect and review the current state before retrying.');
    } finally {
      delete form.dataset.busy; form.removeAttribute('aria-busy'); pendingForm = null;
      locked.forEach(control => { control.disabled = false; });
      updateSelection();
      initInfiniteLibrary();
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


def _navigation(active, frame=None):
    groups = (
        ("Your frame", NAVIGATION[:3]),
        ("Collection", NAVIGATION[3:4]),
        ("Setup & health", NAVIGATION[4:]),
    )
    sections = []
    for label, items in groups:
        links = []
        for key, url, text in items:
            if frame:
                url += "?" + urlencode({"frame": frame})
            current = ' aria-current="page"' if key == active else ""
            links.append(f'<a href="{url}"{current}>{text}</a>')
        sections.append('<p class="nav-caption">' + label + "</p>" + "".join(links))
    return '<nav class="owner-nav" aria-label="Frame management">' + "".join(sections) + "</nav>"


def page(title, body, *, active=None, public=False, description=None, frame=None):
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
        navigation = _navigation(active, frame)
        shell = (
            '<aside class="sidebar">'
            + brand
            + ""
            + navigation
            + '<div class="sidebar-foot"><a href="/">View your frame</a><p>A '
            "little nature, every day, for Emily.</p></div></aside>"
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
    if frame and not public and not login:
        heading += (
            '<p class="frame-context">Selected frame <strong>' + escape(frame) + "</strong></p>"
        )
    footer = (
        '<footer class="site-footer"><span>Emviary &middot; '
        "A little nature, every day, for Emily.</span>"
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
