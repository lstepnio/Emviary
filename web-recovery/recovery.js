import {ESPLoader, Transport} from 'esptool-js';
import SparkMD5 from 'spark-md5';
import {loadRecovery, flashRecovery} from './recovery-core.mjs';

const panel = document.querySelector('[data-usb-recovery]');
if (panel) {
  const prepare = panel.querySelector('[data-usb-prepare]');
  const install = panel.querySelector('[data-usb-install]');
  const confirmBoard = panel.querySelector('[data-usb-board]');
  const erase = panel.querySelector('[data-usb-erase]');
  const status = panel.querySelector('[data-usb-status]');
  const progress = panel.querySelector('progress');
  const supported = window.isSecureContext && 'serial' in navigator;
  let bundle;
  let busy = false;
  const setStatus = (message, error = false) => {
    status.textContent = message;
    status.className = error ? 'notice error' : 'notice';
    status.setAttribute('role', error ? 'alert' : 'status');
  };
  const update = () => {
    prepare.disabled = !supported || busy;
    install.disabled = !bundle || !confirmBoard.checked || busy;
    confirmBoard.disabled = busy;
    erase.disabled = busy;
    panel.setAttribute('aria-busy', String(busy));
  };
  confirmBoard.addEventListener('change', update);
  if (!supported) setStatus('USB recovery needs Chrome or Edge on a laptop, over HTTPS.');
  else setStatus('Prepare the installer first. This step does not access your USB device.');
  update();
  prepare.addEventListener('click', async () => {
    busy = true; bundle = undefined; update();
    setStatus('Downloading and verifying the E1002 recovery files…');
    try {
      bundle = await loadRecovery(fetch, crypto.subtle.digest.bind(crypto.subtle), location.origin);
      setStatus(`Emviary ${bundle.manifest.version} verified. Confirm the E1002, then connect and restore.`);
    } catch (error) { setStatus(error.message, true); }
    finally { busy = false; update(); }
  });
  const preventLeave = event => { event.preventDefault(); event.returnValue = ''; };
  install.addEventListener('click', async () => {
    if (busy || !bundle || !confirmBoard.checked) return;
    const eraseAll = erase.checked;
    if (eraseAll && !window.confirm('Erase all local Wi-Fi, cloud connection and saved images? ' +
        'Download the recovery import file first. Cloud settings and artwork remain on the server.')) return;
    busy = true; update();
    progress.hidden = false; progress.value = 0;
    window.addEventListener('beforeunload', preventLeave);
    let transport;
    try {
      // The port chooser must run directly from this click's user activation.
      const port = await navigator.serial.requestPort();
      transport = new Transport(port, false);
      const loader = new ESPLoader({transport, baudrate: 115200, debugLogging: false,
        terminal: {clean() {}, write() {}, writeLine() {}}});
      setStatus('Connecting to the frame. Keep USB connected and this tab open.');
      const restarted = await flashRecovery(loader, transport, bundle.files, eraseAll,
        data => SparkMD5.ArrayBuffer.hash(data.buffer.slice(data.byteOffset,
          data.byteOffset + data.byteLength)),
        (index, written, total) => {
          progress.value = (index + written / total) / bundle.files.length * 100;
          setStatus(`Restoring firmware, part ${index + 1} of ${bundle.files.length}: ` +
            `${Math.round(written / total * 100)}%. Keep USB connected.`);
        });
      progress.value = 100;
      setStatus('Firmware written and verified. ' +
        (restarted ? 'The frame is restarting. ' : 'Press the green wake button to restart. ') +
        (eraseAll ? 'Follow the Wi-Fi and recovery import steps below.' :
          'Saved settings were preserved. If setup appears, follow the recovery steps below.') +
        ' Confirm the picture returns and Last contact advances in Overview.');
    } catch (error) {
      if (error.name === 'NotFoundError') setStatus('No USB device selected. Nothing was written.');
      else setStatus('Recovery stopped: ' + error.message +
        ' Check the data cable, close other serial apps, and retry. ' +
        'The same installer can recover an interrupted flash.', true);
      if (transport) await transport.disconnect().catch(() => {});
    } finally {
      window.removeEventListener('beforeunload', preventLeave);
      busy = false; update();
    }
  });
}
