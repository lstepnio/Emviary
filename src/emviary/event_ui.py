"""Small image-led calendar cards and immediate, reversible enable controls."""

from html import escape

EVENT_CSS = """
.special-days{padding:0;border:0;background:transparent;box-shadow:none}
.special-days-intro{margin-bottom:20px;color:var(--muted)}
.event-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:18px}
.event-toolbar p{margin:0}.event-toolbar a{white-space:nowrap}
.event-card-image{display:block;box-sizing:border-box}
.event-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;align-items:start}
.event-card{border:1px solid var(--line);border-radius:16px;background:var(--surface);
overflow:hidden}
.event-card-header{display:block}
.event-card-image{height:180px;width:100%;object-fit:contain;background:#f3f1e9;padding:12px}
.event-card-copy{padding:18px 18px 12px}.event-card-copy h3{font-size:18px;margin-bottom:5px}
.event-card-date{font-size:14px;margin-bottom:4px}.event-card-repeat{font-size:12px;color:var(--muted)}
.event-card-message{font-size:13px;color:var(--muted);margin:9px 0 0}
.event-card-controls{display:flex;align-items:center;gap:12px;padding:0 18px 14px}
.event-card-controls form{margin:0}.event-card-controls button{padding:6px 10px;font-size:12px}
.event-toggle-form{margin-left:auto!important}.event-toggle{display:flex;align-items:center;gap:7px;
font-size:12px;cursor:pointer;margin:0}.event-toggle input{appearance:none;width:34px;height:20px;
border-radius:20px;background:#bec7bf;position:relative;cursor:pointer;flex-shrink:0;margin:0}
.event-toggle input:before{content:'';position:absolute;background:white;width:14px;height:14px;
border-radius:50%;left:3px;top:3px;transition:transform .15s}
.event-toggle input:checked{background:var(--accent)}
.event-toggle input:checked:before{transform:translateX(14px)}
.event-toggle input:disabled{opacity:.5;cursor:wait}
.event-toggle-message{font-size:12px;margin:0 18px 12px}
.event-card .event-editor{border:0;border-top:1px solid var(--line);border-radius:0;padding:0}
.event-card .event-editor>summary{padding:10px 18px;font-size:13px;min-height:0}
.event-card .event-editor[open]>summary{margin-bottom:0}.event-editor-content{padding:18px}
.event-editor-content>h3{display:none}.event-editor-content .grid{grid-template-columns:1fr}
.event-secondary{margin-top:24px;display:flex;flex-wrap:wrap;gap:14px;align-items:flex-start}
.event-secondary>details{width:100%;margin:0}.event-secondary>details>summary{font-size:14px}
.event-secondary #event-new{order:-1}
.event-secondary>details[open]{background:var(--surface);padding:18px}
.event-art-secondary{margin-top:20px}.event-art-secondary>summary{font-size:14px}
@media(max-width:480px){.event-cards{grid-template-columns:1fr}
.event-toolbar{flex-wrap:wrap}.event-card-controls{flex-wrap:wrap}
.event-card-copy{padding:14px}
.event-card-controls{padding:0 14px 12px}}
"""

EVENT_JAVASCRIPT = r"""
(() => {
  if (window.__emviaryEventToggles) return;
  window.__emviaryEventToggles = true;
  let queue = Promise.resolve();
  document.addEventListener('click', event => {
    const add = event.target.closest('[data-event-add]');
    if (!add) return;
    event.preventDefault();
    const editor = document.getElementById('event-new');
    editor.open = true; editor.scrollIntoView({behavior:'smooth', block:'start'});
    editor.querySelector('[name=label]').focus({preventScroll:true});
  });
  document.addEventListener('change', event => {
    if (event.target.matches('[name=date_rule]')) {
      const form = event.target.form, recurring = event.target.value === 'nth_weekday';
      const repeat = form.querySelector('[data-event-repeat]');
      repeat.disabled = recurring; if (recurring) repeat.checked = true;
      form.querySelector('[data-event-rule-repeat]').disabled = !recurring;
      return;
    }
    const input = event.target.closest('[data-event-toggle]');
    if (!input) return;
    const form = input.form, desired = input.checked, previous = !desired;
    const message = form.closest('.event-card').querySelector('[data-event-toggle-message]');
    input.disabled = true;
    message.hidden = false; message.textContent = 'Saving…';
    queue = queue.then(async () => {
      try {
        const auth = await fetch('/manage/session', {credentials:'same-origin',
          cache:'no-store', headers:{Accept:'application/json'},
          signal:AbortSignal.timeout(15000)});
        if (auth.status === 401) throw new Error('Your session expired. Sign in in another ' +
          'tab, then retry this change.');
        if (!auth.ok) throw new Error('Sign-in could not be checked. Try again.');
        const current = await auth.json();
        document.querySelectorAll('form input[name="csrf"]').forEach(field => {
          if (!/\/(login|logout)$/.test(new URL(field.form.action).pathname)) {
            field.value = current.csrf;
          }
        });
        const data = new FormData(form); data.set('enabled', desired ? 'yes' : 'no');
        const response = await fetch(form.action, {method:'POST', body:new URLSearchParams(data),
          headers:{Accept:'application/json'}, credentials:'same-origin',
          signal:AbortSignal.timeout(15000)});
        if (response.status === 409) throw new Error('Settings changed in another tab. ' +
          'Reload before saving again.');
        if (response.status === 401 || response.status === 403) throw new Error(
          'Sign in again, then reload this page before saving.');
        if (!response.ok) throw new Error('Could not save. Try again shortly.');
        const saved = await response.json();
        const base = form.action.slice(0, form.action.indexOf('/special-days/'));
        document.querySelectorAll('form').forEach(other => {
          if (!other.action.startsWith(base + '/')) return;
          const revision = other.querySelector('[name="frame_revision"]');
          if (revision) revision.value = saved.config_revision;
        });
        const editor = form.closest('.event-card')
          .querySelector('[data-event-editor] [name="enabled"]');
        if (editor) editor.checked = saved.enabled;
        message.hidden = true;
      } catch (error) {
        input.checked = previous;
        message.textContent = error instanceof TypeError || error.name === 'TimeoutError'
          ? 'The change could not be confirmed. Reload to check its saved state before retrying.'
          : error.message;
      } finally { input.disabled = false; }
    });
  });
})();
"""


def card_start(day, frame_id, csrf, next_date, artwork, hidden):
    """The thumbnail represents saved artwork; automatic selection is labeled explicitly."""
    identifier = escape(frame_id, quote=True)
    day_id = escape(day["id"], quote=True)
    if artwork:
        art_id = escape(artwork["id"], quote=True)
        source = (
            f"/manage/event-art/{art_id}/thumbnail"
            if artwork.get("event_only")
            else f"/art-thumbnail/{art_id}"
        )
        image_label = artwork["common_name"]
    else:
        source, image_label = "/favicon.svg", "Seasonal artwork"
    repeat = "Yearly" if day.get("annual") or day.get("recurrence") else "One time"
    checked = " checked" if day["enabled"] else ""
    return (
        '<article class="event-card"><div class="event-card-header">'
        f'<img class="event-card-image" loading="lazy" src="{source}" '
        f'alt="{escape(image_label, quote=True)}"><div class="event-card-copy">'
        f'<h3>{escape(day["label"])}</h3><p class="event-card-date">'
        f'{escape(next_date.strftime("%b %-d, %Y"))}</p><span class="event-card-repeat">'
        f"{repeat}"
        + (" · Seasonal artwork" if not artwork else "")
        + "</span>"
        + (
            f'<p class="event-card-message">{escape(day["message"])}</p>'
            if day.get("message")
            else ""
        )
        + '</div></div><div class="event-card-controls">'
        f'<form method="post" action="/manage/frames/{identifier}/special-days/{day_id}/preview">'
        + hidden(csrf)
        + '<button class="secondary">Test on frame</button></form>'
        f'<form class="event-toggle-form" method="post" '
        f'action="/manage/frames/{identifier}/special-days/{day_id}/enabled">'
        + hidden(csrf)
        + '<label class="event-toggle"><span>Enabled</span>'
        f'<input type="checkbox" name="enabled" value="yes" data-event-toggle{checked} '
        f'aria-label="Enable {escape(day["label"], quote=True)}"></label>'
        "<noscript><button>Save</button></noscript></form></div>"
        '<p class="event-toggle-message" data-event-toggle-message role="status" hidden></p>'
    )
