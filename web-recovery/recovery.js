import {ESPLoader, Transport} from 'esptool-js';
import SparkMD5 from 'spark-md5';
import {loadRecovery, recoverWithRetries, waitForFrame, cloudSettingsFile, RecoveryTargetError, transferProgress, showTransferSummary} from './recovery-core.mjs';

const panel = document.querySelector('[data-usb-recovery]');
if (panel) {
  const start = panel.querySelector('[data-usb-start]');
  const retryWake = panel.querySelector('[data-usb-wake]');
  const fresh = panel.querySelector('[data-usb-cloud]');
  const status = panel.querySelector('[data-usb-status]');
  const progress = panel.querySelector('progress');
  const frame = panel.dataset.frame;
  const supported = window.isSecureContext && 'serial' in navigator;
  let bundle, port, busy = false, since, connected;
  const digest = crypto.subtle.digest.bind(crypto.subtle);
  const resumeKey = 'emviary-usb-verified:' + frame;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const setStatus = (message, error = false) => {
    status.textContent = message;
    status.className = error ? 'notice error' : 'notice';
    status.setAttribute('role', error ? 'alert' : 'status');
  };
  const step = name => {
    panel.querySelectorAll('[data-usb-step]').forEach(item => {
      if (item.dataset.usbStep === name) item.setAttribute('aria-current', 'step');
      else item.removeAttribute('aria-current');
    });
  };
  const update = () => {
    start.disabled = !supported || !bundle || busy;
    retryWake.disabled = busy;
    [...fresh.elements].forEach(input => { input.disabled = busy; });
    panel.setAttribute('aria-busy', String(busy));
  };
  const statusUrl = () => '/manage/usb-recovery/status/' + encodeURIComponent(frame) +
    (since ? '?since=' + encodeURIComponent(since) : '');
  const verifiedConnection = result => {
    connected = result;
    panel.querySelector('[data-usb-wake-panel]').hidden = true;
    fresh.hidden = true;
    progress.hidden = true;
    step('finish');
    const preview = panel.querySelector('[data-usb-preview]');
    if (result.preview_url) { preview.src = result.preview_url; preview.hidden = false; }
    panel.querySelector('[data-usb-finish]').hidden = false;
    setStatus('Your frame is connected to Emviary and fetching its picture. ' +
      'Check the display before disconnecting USB.');
    start.textContent = 'Run recovery again';
  };
  const waitOnline = async (duration = 120000) => {
    step('connect'); progress.hidden = true;
    const result = await waitForFrame(fetch, statusUrl(), seconds => {
      setStatus('Firmware restored. Waiting for the frame to connect and fetch its picture. ' +
        'Keep USB connected. Checking for up to ' + seconds + ' more seconds.');
    }, duration);
    if (result) { verifiedConnection(result); return true; }
    return false;
  };
  const restart = async () => {
    let opened = false;
    try {
      await port.open({baudRate: 115200}); opened = true;
      // Simultaneous signals avoid the inter-signal gap that can enter download mode.
      await port.setSignals({dataTerminalReady: false, requestToSend: true});
      await sleep(120);
      await port.setSignals({dataTerminalReady: false, requestToSend: false});
      await sleep(120);
    } finally { if (opened) await port.close().catch(() => {}); }
  };
  const escalate = message => {
    const wake = panel.querySelector('[data-usb-wake-panel]');
    wake.hidden = false;
    wake.querySelector('p').textContent = 'Press the green wake button once, keeping USB connected.';
    retryWake.textContent = 'I pressed the green button';
    fresh.hidden = false;
    setStatus(message, true);
  };
  const afterWrite = async restarted => {
    if (!restarted) setStatus('Firmware verified. Restarting the frame.');
    if (!restarted) await restart().catch(() => {});
    if (await waitOnline()) return;
    setStatus('The frame has not connected yet. Trying one more restart.');
    await restart().catch(() => {});
    if (await waitOnline(60000)) return;
    escalate('Firmware is restored, but the frame has not connected. ' +
      'Press the green wake button once. If its saved Wi-Fi no longer works, restore settings from the cloud below.');
  };
  const flash = async files => {
    step('restore'); progress.hidden = false; progress.value = 0;
    const info = port.getInfo();
    const key = 'emviary-usb-rate:' + frame + ':' + (info.usbVendorId || '') + ':' + (info.usbProductId || '');
    let preferred = 460800, usedRate;
    try {
      const cached = Number(sessionStorage.getItem(key));
      if ([460800,230400,115200].includes(cached)) preferred = cached;
    } catch {} // Learning is optional; private/managed browsers can disable storage.
    const began = performance.now();
    const result = await recoverWithRetries((attempt, baud) => {
      usedRate = baud;
      const transport = new Transport(port, false);
      // ESPLoader always performs initial ROM sync at 115200 before changing rate.
      const loader = new ESPLoader({transport, baudrate: baud, debugLogging: false,
        terminal: {clean() {}, write() {}, writeLine() {}}});
      return {loader, transport};
    }, files, files.length === 5,
    data => SparkMD5.ArrayBuffer.hash(data.buffer.slice(data.byteOffset,
      data.byteOffset + data.byteLength)),
    (index, written, total) => {
      progress.value = transferProgress(files, index, written, total);
      setStatus('Writing firmware: ' + Math.round(progress.value) + '%. Keep USB connected.');
    }, attempt => {
      progress.value = 0;
      setStatus(attempt === 1 ? 'Checking your USB connection…' :
        'Trying a steadier USB connection (' + attempt + ' of 3)…');
    }, sleep, preferred);
    // Persist verified completion before optional UI decoration. A reload can resume
    // the connection check without writing the firmware again.
    try {
      sessionStorage.setItem(key, String(usedRate));
      sessionStorage.setItem(resumeKey, JSON.stringify({since, version: bundle.manifest.version}));
    } catch {}
    try { showTransferSummary(panel, usedRate, Math.round((performance.now() - began) / 1000)); } catch {}
    return result;
  };
  const preventLeave = event => { event.preventDefault(); event.returnValue = ''; };
  const run = async (selected, nvs) => {
    port = selected; busy = true; update();
    panel.querySelector('[data-usb-finish]').hidden = true;
    panel.querySelector('[data-usb-preview]').hidden = true;
    panel.querySelector('[data-usb-wake-panel]').hidden = true;
    fresh.hidden = true;
    let written = false;
    try {
      const baseline = await fetch('/manage/usb-recovery/status/' + encodeURIComponent(frame),
        {cache: 'no-store'});
      if (!baseline.ok) throw new Error('Sign in again before recovering the frame.');
      since = (await baseline.json()).checked_at;
      window.addEventListener('beforeunload', preventLeave);
      let restarted;
      try {
        const files = nvs ? [...bundle.files.slice(0, 2), nvs, ...bundle.files.slice(2)] : bundle.files;
        restarted = await flash(files);
      } finally {
        window.removeEventListener('beforeunload', preventLeave);
        nvs?.data.fill(0);
      }
      written = true; progress.value = 100;
      await afterWrite(restarted);
    } catch (error) {
      if (error instanceof RecoveryTargetError) {
        setStatus(error.message, true);
        if (written) {
          const wake = panel.querySelector('[data-usb-wake-panel]'); wake.hidden = false;
          wake.querySelector('p').textContent = 'Firmware is verified. Check the cloud connection again when Emviary is ready.';
          retryWake.textContent = 'Check connection again';
        }
      } else if (written) escalate(error.message);
      else setStatus(error.message + ' Check that USB is connected and other serial apps are closed, then retry.', true);
    } finally { busy = false; update(); }
  };
  start.addEventListener('click', async () => {
    if (busy || !bundle) return;
    try {
      // Port selection is the browser's unavoidable permission step, directly from a click.
      const selected = await navigator.serial.requestPort();
      await run(selected);
    } catch (error) {
      setStatus(error.name === 'NotFoundError' ? 'No frame selected. Nothing was changed.' :
        'USB could not be opened. Check the cable and try again.', true);
    }
  });
  retryWake.addEventListener('click', async () => {
    if (busy || !since) return;
    busy = true; update();
    try {
      if (!await waitOnline(60000)) escalate('The frame still has not connected. ' +
        'Restore its saved cloud settings below, or try a different USB data cable.');
    } catch (error) { setStatus(error.message, true); }
    finally { busy = false; update(); }
  });
  fresh.addEventListener('submit', async event => {
    event.preventDefault(); event.stopPropagation();
    if (busy || !bundle || !fresh.querySelector('[name="replace_local_settings"]').checked) return;
    if (!window.confirm('Replace local Wi-Fi, settings and saved images with the cloud configuration? ' +
        'Your artwork and special days on Emviary will stay unchanged.')) return;
    let nvs;
    try {
      const selected = port || await navigator.serial.requestPort();
      busy = true; update();
      const response = await fetch('/manage/session', {cache: 'no-store'});
      if (!response.ok) throw new Error('Sign in again before restoring cloud settings.');
      const auth = await response.json();
      const data = new FormData(fresh); data.set('csrf', auth.csrf);
      // Controls are disabled for the duration, so collect their values explicitly.
      ['ssid', 'password'].forEach(name => data.set(name, fresh.querySelector('[name="' + name + '"]').value));
      data.set('replace_local_settings', 'yes');
      if (fresh.querySelector('[name="open_network"]').checked) data.set('open_network', 'on');
      const seed = await fetch('/manage/usb-recovery/cloud-settings/' + encodeURIComponent(frame),
        {method: 'POST', body: new URLSearchParams(data)});
      const payload = await seed.json();
      if (!seed.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail :
        'Cloud settings could not be prepared. Try again.');
      nvs = await cloudSettingsFile(payload, frame, digest);
      const password = panel.querySelector('[data-usb-local-password]');
      password.textContent = payload.local_password;
      password.closest('details').hidden = false;
      fresh.querySelector('[name="password"]').value = '';
      await run(selected, nvs);
    } catch (error) { nvs?.data.fill(0); setStatus(error.message, true); }
    finally { busy = false; update(); }
  });
  panel.querySelector('[data-usb-good]').addEventListener('click', () => {
    if (!connected) return;
    setStatus('Recovery complete. You can disconnect USB. Your frame will follow its saved schedule.');
    panel.querySelector('[data-usb-finish]').hidden = true;
    try { sessionStorage.removeItem(resumeKey); } catch {}
  });
  panel.querySelector('[data-usb-not-yet]').addEventListener('click', () => {
    escalate('The frame is connected. Give its color display a minute to finish refreshing. ' +
      'If the picture still does not appear, retry recovery before restoring cloud settings.');
  });
  if (!supported) {
    setStatus('Open this page in Chrome or Edge on a laptop to recover over USB.', true);
    update();
  } else {
    step('prepare'); setStatus('Preparing your frame’s recovery files…'); update();
    Promise.all([
      loadRecovery(fetch, digest, location.origin),
      fetch(statusUrl(), {cache: 'no-store'}).then(async response => {
        if (!response.ok) throw new Error('Sign in to recover this frame.');
        return response.json();
      }),
    ]).then(([ready, metadata]) => {
      bundle = ready;
      const options = panel.querySelector('[data-usb-networks]');
      [...new Set([metadata.suggested_network, ...metadata.network_names].filter(Boolean))]
        .forEach(name => { const option = document.createElement('option'); option.value = name; options.append(option); });
      fresh.querySelector('[name="ssid"]').value = metadata.suggested_network || metadata.network_names[0] || '';
      setStatus('Ready. Connect your reTerminal E1002 with a USB data cable, then choose Recover frame.');
      try {
        const saved = JSON.parse(sessionStorage.getItem(resumeKey));
        if (saved?.version === bundle.manifest.version && Date.now() - Date.parse(saved.since) < 86400000) {
          since = saved.since;
          const wake = panel.querySelector('[data-usb-wake-panel]'); wake.hidden = false;
          wake.querySelector('p').textContent = 'Firmware was already verified. Continue checking its connection without flashing again.';
          retryWake.textContent = 'Check connection again';
          setStatus('Firmware verified. Check the connection to finish recovery.');
        }
      } catch {}
      // Also allow checking an installation completed by an older recovery page.
      if (!since) {
        since = new Date(Date.now() - 600000).toISOString();
        const wake = panel.querySelector('[data-usb-wake-panel]'); wake.hidden = false;
        wake.querySelector('p').textContent = 'Already restored the firmware? Check its connection without writing it again.';
        retryWake.textContent = 'Check connection again';
      }
      update();
    }).catch(error => setStatus(error.message + ' Reload this page to try again.', true));
  }
}
