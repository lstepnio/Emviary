import test from 'node:test';import assert from 'node:assert/strict';
import {recoveryCopy,renderRecovery} from './recovery-ui.mjs';
test('connection wording follows evidence, without a countdown or unsupported Wi-Fi claim',()=>{
  assert.equal(recoveryCopy({state:'connecting',evidence:{}}).title,'Reconnecting your frame');
  assert.equal(recoveryCopy({state:'connecting',evidence:{wifi_connected:true}}).title,'Getting your picture');
  assert.equal(recoveryCopy({state:'connecting',evidence:{image:'verified',panel:'pending'}}).title,'Refreshing your picture');
  assert.doesNotMatch(recoveryCopy({state:'connecting',elapsed_ms:60000}).message,/seconds|Step 3|Wi-Fi is connected/);
});
test('failure copy directs the relevant action and does not recommend destructive repairs for cloud or display trouble',()=>{
  assert.match(recoveryCopy({state:'needs_attention',error:{code:'port_busy'}}).message,/Close other/);
  assert.doesNotMatch(recoveryCopy({state:'needs_attention',error:{code:'cloud_unverified'}}).message,/restore|erase|reinstall/i);
  assert.match(recoveryCopy({state:'finished'}).message,/unplug USB/);
});
test('missing optional decoration does not alter verified progress',()=>{
  const panel={dataset:{},querySelector:()=>null,querySelectorAll:()=>[]};
  assert.doesNotThrow(()=>renderRecovery(panel,{state:'firmware_verified'}));
  assert.equal(panel.dataset.recoveryState,'firmware_verified');
});
