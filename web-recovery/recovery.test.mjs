import assert from 'node:assert/strict';
import {test} from 'node:test';
import {webcrypto} from 'node:crypto';
import {flashRecovery, loadRecovery} from './recovery-core.mjs';

function fixture() {
  const written = [];
  let disconnected = 0;
  const loader = {
    chip: {CHIP_NAME: 'ESP32-S3'}, IS_STUB: true,
    async main() { return 'ESP32-S3 (QFN56) (revision v0.2)'; },
    async detectFlashSize() { return '32MB'; },
    async getSecurityInfo() { return {parsedFlags: {SECURE_BOOT_EN: false}, flashCryptCnt: 0}; },
    async writeFlash(options) { written.push(options); },
    async after(mode) { assert.equal(mode, 'hard_reset'); },
  };
  const transport = {async disconnect() { disconnected++; }};
  return {loader, transport, written, disconnected: () => disconnected};
}

test('repair preserves local data and verifies writes, even with verbose chip description', async () => {
  const f = fixture();
  const files = [{address: 0x20000, data: new Uint8Array([1,2,3])}];
  const md5 = () => 'digest';
  assert.equal(await flashRecovery(f.loader, f.transport, files, false, md5, () => {}), true);
  assert.equal(f.written[0].eraseAll, false);
  assert.equal(f.written[0].fileArray, files);
  assert.equal(f.written[0].calculateMD5Hash, md5);
  assert.equal(f.written[0].flashMode, 'keep');
  assert.equal(f.disconnected(), 1);
});

test('full erase is opt-in and transfer failure always releases USB', async () => {
  const f = fixture();
  await flashRecovery(f.loader, f.transport, [], true, () => '', () => {});
  assert.equal(f.written[0].eraseAll, true);
  f.loader.writeFlash = async () => { throw new Error('Disconnected cable'); };
  await assert.rejects(flashRecovery(f.loader, f.transport, [], false), /Disconnected cable/);
  assert.equal(f.disconnected(), 2);
});

test('wrong chip, insufficient memory and secure device are rejected before writing', async () => {
  for (const variant of ['chip', 'memory', 'secure']) {
    const f = fixture();
    if (variant === 'chip') f.loader.chip.CHIP_NAME = 'ESP32';
    if (variant === 'memory') f.loader.detectFlashSize = async () => '8MB';
    if (variant === 'secure') f.loader.secureDownloadMode = true;
    await assert.rejects(flashRecovery(f.loader, f.transport, [], false), /Nothing was written/);
    assert.equal(f.written.length, 0);
    assert.equal(f.disconnected(), 1);
  }
});

test('reset failure is distinct from a failed flash', async () => {
  const f = fixture();
  f.loader.after = async () => { throw new Error('Reset unavailable'); };
  assert.equal(await flashRecovery(f.loader, f.transport, [], false), false);
  assert.equal(f.written.length, 1);
  assert.equal(f.disconnected(), 1);
});

test('secure-boot and flash-encryption devices are refused before erasing or writing', async () => {
  for (const security of [
    {parsedFlags: {SECURE_BOOT_EN: true}, flashCryptCnt: 0},
    {parsedFlags: {SECURE_BOOT_EN: false}, flashCryptCnt: 1},
  ]) {
    const f = fixture();
    f.loader.getSecurityInfo = async () => security;
    await assert.rejects(flashRecovery(f.loader, f.transport, [], true), /Nothing was written/);
    assert.equal(f.written.length, 0);
    assert.equal(f.disconnected(), 1);
  }
});

test('download checks hashes, addresses and same-origin files before USB is requested', async () => {
  const data = new Uint8Array([1,2,3]);
  const digest = webcrypto.subtle.digest.bind(webcrypto.subtle);
  const sha256 = Buffer.from(await digest('SHA-256', data)).toString('hex');
  const manifest = {
    board: 'seeedstudio_reterminal_e1002', chip: 'ESP32-S3', flash_size: '32MB',
    flash_mode: 'dio', flash_freq: '80m',
    parts: [0, 0x8000, 0xf000, 0x20000].map(address => ({
      address, size: 3, sha256, url: '/manage/usb-recovery/part.bin',
    })),
  };
  const fetcher = async url => url.endsWith('/manifest') ?
    {ok: true, async json() { return manifest; }} :
    {ok: true, async arrayBuffer() { return data.buffer; }};
  assert.equal((await loadRecovery(fetcher, digest, 'https://emviary.majjix.com')).files.length, 4);
  manifest.parts[0].sha256 = 'bad';
  await assert.rejects(loadRecovery(fetcher, digest, 'https://emviary.majjix.com'), /verification failed/);
  manifest.parts[0].sha256 = sha256;
  manifest.parts[0].address = 0x9000; // NVS must never be written in normal repair.
  await assert.rejects(loadRecovery(fetcher, digest, 'https://emviary.majjix.com'), /layout/);
  manifest.parts[0].address = 0;
  manifest.parts[0].url = 'https://untrusted.example/firmware.bin';
  await assert.rejects(loadRecovery(fetcher, digest, 'https://emviary.majjix.com'), /layout/);
});
