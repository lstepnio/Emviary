// All files are verified before opening a serial port. Keep each flash region separate:
// a merged image would overwrite saved NVS settings in the gaps between regions.
export async function loadRecovery(fetcher, digest, origin) {
  const response = await fetcher('/manage/usb-recovery/manifest', {cache: 'no-store'});
  if (!response.ok) throw new Error('Sign in again and retry preparing the installer.');
  const manifest = await response.json();
  const addresses = [0, 0x8000, 0xf000, 0x20000];
  const limits = [0x8000, 0x1000, 0x2000, 0x380000];
  if (manifest.board !== 'seeedstudio_reterminal_e1002' || manifest.chip !== 'ESP32-S3' ||
      manifest.flash_size !== '32MB' || manifest.flash_mode !== 'dio' ||
      manifest.flash_freq !== '80m' || manifest.parts?.length !== 4) {
    throw new Error('The recovery bundle does not match the E1002. Nothing was written.');
  }
  const files = [];
  for (const [index, part] of manifest.parts.entries()) {
    const url = new URL(part.url, origin);
    if (url.origin !== origin || !url.pathname.startsWith('/manage/usb-recovery/') ||
        part.address !== addresses[index] || !Number.isInteger(part.size) ||
        part.size <= 0 || part.size > limits[index]) {
      throw new Error('Invalid recovery layout. Nothing was written.');
    }
    const download = await fetcher(url.href, {cache: 'no-store'});
    if (!download.ok) throw new Error('Firmware download failed. Sign in and try again.');
    const data = new Uint8Array(await download.arrayBuffer());
    const hash = Array.from(new Uint8Array(await digest('SHA-256', data)))
      .map(byte => byte.toString(16).padStart(2, '0')).join('');
    if (data.length !== part.size || hash !== part.sha256) {
      throw new Error('Firmware verification failed. Nothing was written. Try preparing again.');
    }
    files.push({address: part.address, data});
  }
  return {manifest, files};
}

export async function flashRecovery(loader, transport, files, eraseAll, md5, progress, mode = 'default_reset') {
  try {
    await loader.main(mode);
    if (loader.chip?.CHIP_NAME !== 'ESP32-S3' || loader.secureDownloadMode ||
        !loader.IS_STUB || await loader.detectFlashSize() !== '32MB') {
      throw new RecoveryTargetError('This device does not match the E1002 chip and memory. Nothing was written.');
    }
    const security = await loader.getSecurityInfo();
    if (security.parsedFlags.SECURE_BOOT_EN || security.flashCryptCnt !== 0) {
      throw new RecoveryTargetError('This device uses custom boot or encryption security. Nothing was written.');
    }
    // READ_FLASH sends a final 16-byte digest after the data packets. Consume
    // and verify it here before another command, matching Espressif's protocol.
    // Probe public application bytes, never local credentials, before any erase.
    if (typeof loader.readFlash === 'function') {
      const sample = await loader.readFlash(0x20000, 16384);
      try {
        const rawDigest = await transport.read(3000);
        const expected = Array.from(rawDigest).map(b => b.toString(16).padStart(2, '0')).join('');
        if (sample.length !== 16384 || rawDigest.length !== 16 || md5(sample) !== expected) {
          throw new Error('USB transfer check failed. Trying a steadier connection.');
        }
      } finally { sample.fill(0); }
    }
    await loader.writeFlash({
      fileArray: files, flashMode: 'keep', flashFreq: 'keep', flashSize: 'keep',
      eraseAll, compress: true, calculateMD5Hash: md5, reportProgress: progress,
    });
    // Keep headers from the hash-verified build unchanged. Flash geometry was
    // validated before writing, and the build already carries DIO / 80 MHz / 32 MB.
    try {
      await loader.after('hard_reset');
      return true;
    } catch {
      return false; // Writing and verification succeeded; only automatic reset failed.
    }
  } finally {
    await transport.disconnect().catch(() => {});
  }
}

export class RecoveryTargetError extends Error {}
export const RECOVERY_BAUD_RATES = Object.freeze([460800, 230400, 115200]);

export async function recoverWithRetries(create, files, eraseAll, md5, progress, report,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), preferredBaud = 460800) {
  const rates = RECOVERY_BAUD_RATES.filter(rate => rate <= preferredBaud);
  if (!rates.length) rates.push(115200);
  let failure;
  for (let attempt = 0; attempt < 3; attempt++) {
    const baud = rates[Math.min(attempt, rates.length - 1)];
    report(attempt + 1, baud);
    const {loader, transport} = create(attempt, baud);
    try {
      return await flashRecovery(loader, transport, files, eraseAll, md5, progress,
        'default_reset');
    } catch (error) {
      if (error instanceof RecoveryTargetError) throw error;
      failure = error;
      if (attempt < 2) await sleep(800);
    }
  }
  throw failure;
}

export async function waitForFrame(fetcher, url, report, duration = 120000,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)), now = () => Date.now()) {
  const end = now() + duration;
  while (now() < end) {
    try {
      const response = await fetcher(url, {cache: 'no-store', signal: AbortSignal.timeout(7000)});
      if (response.status === 401) throw new RecoveryTargetError('Sign in to verify the frame.');
      if (response.ok) {
        const result = await response.json();
        if (result.cloud_ready === false) throw new RecoveryTargetError(
          "The cloud artwork is not ready. The firmware is restored; check Emviary again shortly.");
        if (result.connected) return result;
      }
    } catch (error) {
      if (error instanceof RecoveryTargetError) throw error;
      // A brief service/network failure cannot undo verified flash writes.
    }
    report(Math.max(0, Math.ceil((end - now()) / 1000)));
    await sleep(2500);
  }
  return null;
}

export async function cloudSettingsFile(payload, frame, digest) {
  if (payload.frame_id !== frame || payload.address !== 0x9000 || payload.size !== 0x6000 ||
      typeof payload.data !== 'string' || payload.data.length !== 32768) {
    throw new RecoveryTargetError('Cloud settings do not match this frame. Nothing was erased.');
  }
  const data = Uint8Array.from(atob(payload.data), c => c.charCodeAt(0));
  const hash = Array.from(new Uint8Array(await digest('SHA-256', data)))
    .map(byte => byte.toString(16).padStart(2, '0')).join('');
  if (data.length !== payload.size || hash !== payload.sha256) {
    throw new RecoveryTargetError('Cloud settings verification failed. Nothing was erased.');
  }
  return {address: 0x9000, data};
}

// Progress covers writing bytes only. Verification and connection are separate phases.
export function transferProgress(files, index, written, total) {
  const sizes = files.map(file => file.data.length);
  const size = sizes.reduce((sum, value) => sum + value, 0);
  if (!size || index < 0 || index >= files.length) return 0;
  const fraction = Number.isFinite(written / total) ? Math.max(0, Math.min(1, written / total)) : 0;
  return Math.min(99, 100 * (sizes.slice(0, index).reduce((sum, value) => sum + value, 0) + sizes[index] * fraction) / size);
}

export function showTransferSummary(panel, rate, seconds) {
  const element = panel.querySelector('[data-usb-speed]');
  if (element) element.textContent = 'Verified USB transfer: ' + rate.toLocaleString() +
    ' baud, ' + seconds + ' seconds.';
}
