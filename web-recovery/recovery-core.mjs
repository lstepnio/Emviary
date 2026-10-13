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

export async function flashRecovery(loader, transport, files, eraseAll, md5, progress) {
  try {
    await loader.main();
    if (loader.chip?.CHIP_NAME !== 'ESP32-S3' || loader.secureDownloadMode ||
        !loader.IS_STUB || await loader.detectFlashSize() !== '32MB') {
      throw new Error('This device does not match the E1002 chip and memory. Nothing was written.');
    }
    const security = await loader.getSecurityInfo();
    if (security.parsedFlags.SECURE_BOOT_EN || security.flashCryptCnt !== 0) {
      throw new Error('This device uses custom boot or encryption security. Nothing was written.');
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
