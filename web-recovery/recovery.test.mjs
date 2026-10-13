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

import {recoverWithRetries, waitForFrame, cloudSettingsFile, RecoveryTargetError} from './recovery-core.mjs';

test('three bounded attempts recover serial interruptions without escalating to erase', async () => {
  const calls = [], modes = [], closed = [];
  const result = await recoverWithRetries(attempt => {
    const f = fixture();
    f.loader.main = async mode => { modes.push(mode); if (attempt < 2) throw new Error('Lost USB'); };
    closed.push(f);
    return f;
  }, [], false, () => '', () => {}, attempt => calls.push(attempt), async () => {});
  assert.equal(result, true);
  assert.deepEqual(calls, [1,2,3]);
  assert.deepEqual(modes, ['default_reset','default_reset','default_reset']);
  assert.ok(closed.every(f => f.disconnected() === 1));
  assert.equal(closed[2].written[0].eraseAll, false);
});

test('a wrong device is terminal and exhausted USB failures stop after three attempts', async () => {
  let calls = 0;
  await assert.rejects(recoverWithRetries(() => {
    calls++; const f = fixture(); f.loader.chip.CHIP_NAME = 'ESP32'; return f;
  }, [], false, () => '', () => {}, () => {}, async () => {}), RecoveryTargetError);
  assert.equal(calls, 1);
  calls = 0;
  await assert.rejects(recoverWithRetries(() => {
    calls++; const f = fixture(); f.loader.main = async () => { throw new Error('No cable'); }; return f;
  }, [], false, () => '', () => {}, () => {}, async () => {}), /No cable/);
  assert.equal(calls, 3);
});

test('cloud verification tolerates temporary failures and stops when the target connects', async () => {
  let time = 0, calls = 0;
  const result = await waitForFrame(async () => {
    if (++calls === 1) throw new Error('Offline');
    return {ok:true, async json() { return {connected:calls===3}; }};
  }, '/status', () => {}, 10000, async ms => {time += ms;}, () => time);
  assert.equal(result.connected, true); assert.equal(calls, 3);
  const timeout = await waitForFrame(async () => ({ok:true, async json() {return {connected:false};}}),
    '/status', () => {}, 5000, async ms => {time += ms;}, () => time);
  assert.equal(timeout, null);
  await assert.rejects(waitForFrame(async () => ({status:401}), '/status', () => {}), RecoveryTargetError);
});

test('factory settings must match the chosen frame, NVS range and content hash', async () => {
  const data = new Uint8Array(24576).fill(0xff);
  const digest = webcrypto.subtle.digest.bind(webcrypto.subtle);
  const payload = {frame_id:'emily-e1002',address:0x9000,size:24576,
    sha256:Buffer.from(await digest('SHA-256',data)).toString('hex'),
    data:Buffer.from(data).toString('base64')};
  const file = await cloudSettingsFile(payload, 'emily-e1002', digest);
  assert.equal(file.address, 0x9000); assert.equal(file.data.length,24576);
  for (const change of [{address:0x8000}, {frame_id:'other-frame'}, {sha256:'bad'}, {data:'short'}]) {
    await assert.rejects(cloudSettingsFile({...payload,...change},'emily-e1002',digest), RecoveryTargetError);
  }
});

test('USB speed falls back conservatively and remembers a verified slower preference', async () => {
  const rates = [];
  await recoverWithRetries((attempt, rate) => {
    rates.push(rate); const f = fixture();
    f.loader.main = async () => { if (attempt < 2) throw new Error('Serial noise'); };
    return f;
  }, [], false, () => '', () => {}, () => {}, async () => {});
  assert.deepEqual(rates, [460800,230400,115200]);
  rates.length = 0;
  await recoverWithRetries((attempt, rate) => {
    rates.push(rate); const f = fixture();
    f.loader.main = async () => { if (attempt === 0) throw new Error('Packet error'); };
    return f;
  }, [], false, () => '', () => {}, () => {}, async () => {}, 115200);
  assert.deepEqual(rates, [115200,115200]);
});

test('bulk read/digest probe is verified and consumed before any erase or write', async () => {
  const f = fixture(), data = new Uint8Array(16384).fill(0xab);
  const md5 = () => '00112233445566778899aabbccddeeff';
  f.loader.readFlash = async (address, size) => {
    assert.equal(address,0x20000); assert.equal(size,16384); return data;
  };
  f.transport.read = async () => Uint8Array.from(Buffer.from(md5(),'hex'));
  await flashRecovery(f.loader,f.transport,[],false,md5,()=>{});
  assert.equal(f.written.length,1); assert.ok(data.every(b=>b===0));
  const bad = fixture();
  bad.loader.readFlash = async () => new Uint8Array(16384);
  bad.transport.read = async () => new Uint8Array(16);
  await assert.rejects(flashRecovery(bad.loader,bad.transport,[],true,md5,()=>{}),/transfer check failed/);
  assert.equal(bad.written.length,0); assert.equal(bad.disconnected(),1);
});

import {transferProgress, showTransferSummary} from './recovery-core.mjs';
test('writing progress weights firmware bytes, clamps callbacks, and reserves verification', () => {
  const files = [16, 3, 8, 1500].map(length => ({data: new Uint8Array(length)}));
  assert.ok(transferProgress(files, 2, 8, 8) < 2);
  assert.ok(transferProgress(files, 3, 50, 100) > 49);
  assert.ok(transferProgress(files, 3, 50, 100) < 52);
  assert.equal(transferProgress(files, 3, 200, 100), 99);
  assert.equal(transferProgress(files, 0, 0, 0), 0);
  assert.equal(transferProgress(files, 0, -1, 100), 0);
});
test('missing optional speed decoration cannot invalidate a verified write', () => {
  assert.doesNotThrow(() => showTransferSummary({querySelector: () => null}, 460800, 12));
  const element = {};
  showTransferSummary({querySelector: () => element}, 460800, 12);
  assert.match(element.textContent, /12 seconds/);
});

test('fresh contact from another firmware stops waiting without requesting a Wi-Fi reset', async () => {
  await assert.rejects(waitForFrame(async () => ({ok:true, async json() {
    return {connected:false, fresh_contact:true, reported_firmware:'v0.8.3', expected_firmware:'v0.8.4'};
  }}), '/status', () => {}), /Wi-Fi settings do not need resetting/);
});

import {recoveryPort, restartFrame} from './recovery-core.mjs';
test('wake check reuses one authorized USB adapter and releases reset without writing', async () => {
  const calls = [];
  const port = {getInfo:()=>({usbVendorId:0x1a86}),
    async open(options) {calls.push(['open', options.baudRate]);},
    async setSignals(value) {calls.push(['signals',value]);},
    async close() {calls.push(['close']);}};
  const serial = {async getPorts() {return [port];}, async requestPort() {throw new Error('unnecessary prompt');}};
  assert.equal(await recoveryPort(serial), port);
  await restartFrame(port, async () => {});
  assert.deepEqual(calls, [['open',115200], ['signals',{dataTerminalReady:false,requestToSend:true}],
    ['signals',{dataTerminalReady:false,requestToSend:false}], ['close']]);
  port.setSignals = async () => {throw new Error('USB detached');};
  await assert.rejects(restartFrame(port, async () => {}), /USB detached/);
  assert.deepEqual(calls.at(-1), ['close']);
});
test('ambiguous USB adapters require selection and known ports avoid another prompt', async () => {
  const port = {getInfo:()=>({usbVendorId:0x1a86})}; let prompts = 0;
  const serial = {async getPorts() {return [port,port];}, async requestPort() {prompts++;return port;}};
  assert.equal(await recoveryPort(serial),port); assert.equal(prompts,1);
  assert.equal(await recoveryPort(serial,port),port); assert.equal(prompts,1);
});

test('disconnected saved adapter is replaced by the connected authorized frame without prompting',async()=>{
  const old={connected:false,getInfo:()=>({usbVendorId:0x1a86})};
  const current={connected:true,getInfo:()=>({usbVendorId:0x1a86})};
  const serial={getPorts:async()=>[old,current],requestPort:async()=>{throw new Error('unnecessary picker');}};
  assert.equal(await recoveryPort(serial,old),current);
});
