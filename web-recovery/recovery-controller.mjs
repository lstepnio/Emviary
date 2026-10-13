// Deterministic recovery orchestration. Hardware and authenticated service primitives
// are injected; a rendering failure can never invalidate verified device evidence.
export class RecoveryFault extends Error {
  constructor(code, message, options = {}) { super(message); this.name = 'RecoveryFault'; this.code = code; Object.assign(this, options); }
}
export function classifyRecoveryError(error) {
  if (error instanceof RecoveryFault) return error;
  if (error?.name === 'RecoveryTargetError') return new RecoveryFault('target_refused',error.message,{retryable:false});
  if (error?.name === 'NotFoundError') return new RecoveryFault('permission_cancelled', 'No USB frame selected.', {retryable: false});
  if (error?.name === 'AbortError') return new RecoveryFault('cancelled', 'Recovery stopped.', {retryable: false});
  if (error?.name === 'NetworkError' || error?.code === 'DISCONNECTED') return new RecoveryFault('usb_disconnected', 'Reconnect the same frame to continue.', {retryable: false});
  if (error?.name === 'InvalidStateError') return new RecoveryFault('port_busy', 'Close other serial apps and recovery tabs.', {retryable: true});
  if ([400,401,403].includes(error?.status)) return new RecoveryFault('authentication', 'Sign in again to continue recovery.', {retryable: false});
  return new RecoveryFault(error?.code || 'operation_failed', error?.message || 'Recovery could not finish.', {retryable: true});
}
export const defaultClock = {now: () => Date.now(), setTimeout: (fn, ms) => setTimeout(fn, ms), clearTimeout: id => clearTimeout(id)};
export async function boundedOperation(work, ms, {signal, clock = defaultClock, operation = 'operation'} = {}) {
  const child = new AbortController();
  let timer, listener;
  const stopped = new Promise((_, reject) => {
    listener = () => { child.abort(signal?.reason); reject(signal?.reason instanceof Error ? signal.reason : new RecoveryFault('cancelled', 'Recovery stopped.')); };
    if (signal?.aborted) listener(); else signal?.addEventListener('abort', listener, {once: true});
    timer = clock.setTimeout(() => { const fault = new RecoveryFault('timeout', `${operation} timed out.`, {operation, retryable: true}); child.abort(fault); reject(fault); }, ms);
  });
  try { return await Promise.race([stopped, Promise.resolve().then(() => { if(child.signal.aborted) throw child.signal.reason; return work(child.signal); })]); }
  finally { clock.clearTimeout(timer); signal?.removeEventListener('abort', listener); }
}
const owners = new Map();
const budgets = {prepare: 30000, hello: 5000, identify: 10000, verifyFirmware: 30000, repair: 300000, reset: 5000, begin: 5000, status: 5000, cloud: 10000, end: 5000, release: 3000};
const safeEvidence = value => {
  // Protocol status contains only these non-secret fields. Never serialize traces,
  // injected configuration objects, credentials or transport internals.
  const keys = ['device_identity','boot_id','firmware','board','stage','error','active','configuration_ready','wifi_connected','cloud','image','panel','composition_id','digest','image_id','image_sha256','connected','session_verified','cloud_ready'];
  return Object.fromEntries(keys.filter(k => value?.[k] !== undefined).map(k => [k,value[k]]));
};
export class RecoveryController {
  constructor({frameId, expectedIdentity, expectedFirmware, operations, onEvent = () => {}, storage, clock = defaultClock, sessionId = globalThis.crypto.randomUUID(), nonce = globalThis.crypto.randomUUID(), overallMs = 600000, deadlines = {}}) {
    Object.assign(this, {frameId, expectedIdentity, expectedFirmware, operations, onEvent, storage, clock, sessionId, nonce, overallMs});
    this.deadlines = {...budgets,...deadlines}; this.state = 'idle'; this.verified = {}; this.ledger = {}; this.identity = null; this.activeMs = 0;
    this.key = 'emviary-recovery-v1:' + frameId;
    try { const saved = JSON.parse(storage?.getItem(this.key) || 'null'); if (saved?.frameId === frameId && saved.expectedFirmware === expectedFirmware && saved.expectedIdentity === expectedIdentity && saved.sessionId === sessionId && saved.nonce === nonce) { this.journal = saved; this.identity = saved.identity; this.sessionId = saved.sessionId; this.nonce = saved.nonce; this.ledger = saved.ledger || {}; this.activeMs = saved.activeMs || 0; } } catch {}
  }
  snapshot() { return {schema:1, frameId:this.frameId, expectedIdentity:this.expectedIdentity,expectedFirmware:this.expectedFirmware,sessionId:this.sessionId,nonce:this.nonce,identity:this.identity,state:this.state,verified:{...this.verified},ledger:{...this.ledger},activeMs:this.elapsed()}; }
  elapsed() { return this.activeMs + (this.began == null ? 0 : this.clock.now() - this.began); }
  emit(state, operation, evidence, error) { this.state = state; const event = {session_id:this.sessionId,attempt_id:this.ledger[operation] || 0,device_identity:this.identity,state,phase:state,operation,elapsed_ms:this.elapsed(),evidence:safeEvidence(evidence),error:error ? {code:error.code,message:error.message} : null}; try {this.onEvent(event);} catch {} try {this.storage?.setItem(this.key,JSON.stringify(this.snapshot()));} catch {} }
  async op(name, extra = {}, limitMs = Infinity) {
    if (!this.operations[name]) throw new RecoveryFault('missing_operation', `Recovery operation ${name} is unavailable.`, {retryable:false});
    const remaining = this.overallMs - this.elapsed(); if (remaining <= 0) throw new RecoveryFault('overall_timeout','Recovery reached its active time limit.',{retryable:false});
    this.ledger[name] = (this.ledger[name] || 0) + 1; this.emit(this.state,name);
    return boundedOperation(signal => this.operations[name]({signal,port:this.port,sessionId:this.sessionId,nonce:this.nonce,attempt:this.ledger[name],verified:{...this.verified},...extra}),Math.min(this.deadlines[name] || 10000,remaining,limitMs),{signal:this.abort.signal,clock:this.clock,operation:name});
  }
  checkIdentity(result) {
    const identity = result?.device_identity;
    if (!identity || (this.expectedIdentity && identity !== this.expectedIdentity) || (this.identity && identity !== this.identity)) throw new RecoveryFault('wrong_device','This USB device does not match the selected frame. Nothing was written.',{retryable:false});
    this.identity = identity;
    if (result.board && result.board !== 'seeedstudio_reterminal_e1002') throw new RecoveryFault('wrong_board','This device is not an E1002.',{retryable:false});
    return result;
  }
  checkBoot(result) {
    this.checkIdentity(result);
    if (!result.boot_id || result.firmware !== this.expectedFirmware || result.protocol !== 1) throw new RecoveryFault('boot_unverified','The expected application has not acknowledged startup.',{retryable:false});
    return result;
  }
  async probeBoot() {
    for(let probe=0;probe<3;probe++) {
      try{return this.checkBoot(await this.op('hello'));}
      catch(error) {
        const fault=classifyRecoveryError(error);
        if(!(['operation_busy','not_ready'].includes(fault.code)||(fault.code==='timeout'&&fault.replyTimeout&&fault.writeCompleted))||probe>=2)throw fault;
        this.emit(fault.code==='timeout'?'booting':'application_busy','hello',null,fault);
        await this.delay(1500);
      }
    }
  }
  async run({port, repair = true} = {}) {
    if(this.running) return this.running;
    if (owners.has(this.frameId) && owners.get(this.frameId) !== this) throw new RecoveryFault('tab_conflict','Another recovery owns this frame.',{retryable:false});
    owners.set(this.frameId,this); this.port = port || this.port; this.abort = new AbortController(); this.began = this.clock.now();
    this.running = this.execute(repair).finally(async () => {
      // Abort first so late writes/readers cannot advance state after a timeout.
      this.abort.abort();
      if(this.operations.release) try {await boundedOperation(signal => this.operations.release({port:this.port,signal}),this.deadlines.release,{clock:this.clock,operation:'release'});} catch {}
      this.activeMs = this.elapsed(); this.began = null; owners.delete(this.frameId); this.running = null;
      try {this.storage?.setItem(this.key,JSON.stringify(this.snapshot()));} catch {}
    });
    return this.running;
  }
  async execute(allowRepair) {
    try {
      this.emit('preparing','prepare'); await this.op('prepare');
      let hello;
      this.emit('identifying','hello');
      try {hello = await this.probeBoot();} catch(error) {
        const fault = classifyRecoveryError(error);
        if(['wrong_device','wrong_board','usb_disconnected','cancelled','port_busy','operation_busy','not_ready'].includes(fault.code)) throw fault;
        // Sleeping/slow-starting applications are challenged again after one
        // bounded wake, before entering ROM or considering firmware repair.
        if(fault.code !== 'boot_unverified' && this.operations.reset) {
          this.ledger.wake = (this.ledger.wake || 0) + 1; this.emit('booting','reset');
          await this.op('reset',{wakeOnly:true});
          for(let probe=0;probe<2 && !hello;probe++) {
            try {hello = await this.probeBoot();}
            catch(e) {const f=classifyRecoveryError(e);if(['wrong_device','wrong_board','usb_disconnected','cancelled','port_busy','operation_busy','not_ready'].includes(f.code)) throw f;}
          }
        }
        if(!hello) {
        const identity = this.checkIdentity(await this.op('identify')); this.emit('identified','identify',identity);
        // Reloaded journals are hints only: verify actual regions before skipping.
        if ((this.verified.firmware || this.journal?.verified?.firmware) && this.operations.verifyFirmware) this.verified.firmware = (await this.op('verifyFirmware')) === true;
        if(!this.verified.firmware) {
          if(!allowRepair) throw fault;
          this.emit('repairing','repair');
          while ((this.ledger.repair || 0) < 3) {
            try { const written = await this.op('repair',{baud:[460800,230400,115200][this.ledger.repair || 0]}); if(written?.verified !== true) throw new RecoveryFault('flash_unverified','Firmware writes were not fully verified.',{retryable:false}); this.verified.firmware = true; this.emit('firmware_verified','repair'); break; }
            catch(e) {const f = classifyRecoveryError(e); if(!f.retryable || ['usb_disconnected','wrong_device','wrong_board'].includes(f.code) || this.ledger.repair >= 3) throw f;}
          }
          if(!this.verified.firmware) throw new RecoveryFault('retry_exhausted','The USB transfer retry limit was reached.',{retryable:false});
        }
        this.emit('booting','hello');
        for(let attempt = 0;attempt < 2 && !hello;attempt++) {
          await this.op('reset');
          try {hello = await this.probeBoot();} catch(e) {if(['wrong_device','wrong_board','usb_disconnected','cancelled','operation_busy','not_ready'].includes(classifyRecoveryError(e).code)) throw e;}
        }
        if(!hello) throw new RecoveryFault('boot_unverified','Firmware is verified, but application startup was not confirmed. Keep USB connected.',{retryable:false});
        }
      }
      this.verified.boot = hello.boot_id; this.emit('application_booted','hello',hello);
      let begun = false;
      for(let beginAttempt=0;beginAttempt<3;beginAttempt++) {
        try {await this.op('begin');begun=true;break;}
        catch(error) {
          const fault=classifyRecoveryError(error);
          if(!['operation_busy','not_ready'].includes(fault.code) || beginAttempt >= 2) throw fault;
          this.emit('application_busy','begin',null,fault);
          await this.delay(1500);
        }
      }
      if(!begun) throw new RecoveryFault('operation_busy','The frame is still busy. Continue when its current operation finishes.',{retryable:false});
      this.emit('connecting','status');
      const networkStart = this.clock.now(), networkCap = networkStart + 180000;
      let networkEnd = networkStart + 60000, completedPhase = 0;
      const positiveProof = new Set();
      let status, cloud;
      for(let pipelineAttempt=1;pipelineAttempt<=3;pipelineAttempt++) {
      this.ledger.pipeline = (this.ledger.pipeline || 0) + 1;
      try {
      do {
        try {status = await this.op('status',{},Math.max(1,networkEnd-this.clock.now()));}
        catch(error) {
          if(error.code === 'timeout' && error.replyTimeout && error.writeCompleted && !this.abort.signal.aborted && this.clock.now() < networkEnd) {
            this.emit('connecting','status',status,error);
            await this.delay(Math.min(1500,Math.max(1,networkEnd-this.clock.now())));
            continue;
          }
          throw error;
        }
        this.checkBoot(status);
        if(status.boot_id !== this.verified.boot || status.session_id !== this.sessionId || status.nonce !== this.nonce || !status.active) throw new RecoveryFault('session_mismatch','The frame recovery session changed.',{retryable:false});
        this.emit('connecting','status',status);
        const failed = status.error && !['none','ok','ESP_OK'].includes(status.error);
        if(failed || status.panel === 'error' || status.image === 'error' || status.cloud === 'error') {
          const code = ['nvs','configuration'].includes(status.stage) ? 'configuration_required' :
            ['board','storage','rtc','display'].includes(status.stage) && failed ? (status.stage === 'storage' ? 'storage_failed' : status.stage === 'display' ? 'display_failed' : 'initialization_failed') :
            !status.wifi_connected && status.configuration_ready ? 'wifi_connection_failed' :
            status.panel === 'error' ? 'display_failed' : status.image === 'error' ? 'image_failed' : status.cloud === 'error' ? 'cloud_failed' : String(status.error);
          throw new RecoveryFault(code,'The frame reported a recovery error. Verified firmware is preserved.',{retryable:false});
        }
        // Only newly completed phases or stronger positive evidence extend the
        // connection budget. Repeated status text and toggling states do not.
        const stageRank = {board:1,storage:2,configuration:3,rtc:4,display:5,ready:6,cloud_request:7,image_verified:8,panel:9}[status.stage] || 0;
        let advanced = stageRank > completedPhase;
        completedPhase = Math.max(completedPhase,stageRank);
        for(const [key,proved] of [['configuration',status.configuration_ready],['wifi',status.wifi_connected],['cloud',status.cloud === 'authenticated'],['image',status.image === 'verified'],['panel',status.panel === 'complete']]) {
          if(proved && !positiveProof.has(key)) {positiveProof.add(key);advanced=true;}
        }
        if(advanced) networkEnd=Math.min(networkCap,Math.max(networkEnd,this.clock.now()+60000));
        const initializing = ['boot','board','storage','configuration','rtc_initializing','rtc','display_initializing','display'].includes(status.stage);
        if(!status.configuration_ready && !initializing) throw new RecoveryFault('configuration_required','Saved settings need attention. Firmware remains verified.',{retryable:false});
        if(status.wifi_connected && status.cloud === 'authenticated' && status.image === 'verified' && status.panel === 'complete') break;
        await this.delay(Math.min(1500,Math.max(1,networkEnd-this.clock.now())));
      } while(this.clock.now() < networkEnd);
      if(!(status?.wifi_connected && status.cloud === 'authenticated' && status.image === 'verified' && status.panel === 'complete')) throw new RecoveryFault('network_timeout','The connection or picture could not be verified. Firmware remains verified.',{retryable:false});
      cloud = await this.op('cloud',{bootId:this.verified.boot,imageSha256:status.image_sha256,imageId:status.image_id},Math.max(1,networkEnd-this.clock.now()));
      if(cloud?.session_verified !== true || cloud?.connected !== true) throw new RecoveryFault('cloud_unverified','Emviary has not acknowledged this recovery session.',{retryable:false});
      break;
      } catch(error) {
        const fault=classifyRecoveryError(error);
        const recoverable=['wifi_connection_failed','image_failed','cloud_failed','cloud_unverified','service_error','network_timeout'].includes(fault.code) || (fault.code === 'timeout' && ['cloud','status','STATUS'].includes(fault.operation)) || (fault.code === 'operation_failed' && status?.panel === 'complete');
        if(!recoverable || pipelineAttempt >= 3 || this.clock.now() >= networkEnd || this.clock.now() >= networkCap) throw fault;
        this.emit('connecting','retry_pipeline',status,fault);
        await this.delay(Math.min(1500,Math.max(1,networkEnd-this.clock.now())));
        if(this.clock.now() >= networkEnd) throw fault;
        // Idempotent same-session BEGIN restarts only a failed picture/network
        // pipeline. Firmware, selected device and settings remain untouched.
        await this.op('begin',{},Math.max(1,networkEnd-this.clock.now()));
      }
      }
      this.verified.cloud = true; this.verified.panel = true; this.emit('physical_confirmation','cloud',cloud); return this.snapshot();
    } catch(error) {const fault = classifyRecoveryError(error); this.emit(fault.code === 'usb_disconnected' ? 'paused' : fault.code === 'cancelled' ? 'cancelled' : 'needs_attention',fault.operation || 'recovery',null,fault); throw fault;}
  }
  delay(ms) {
    return boundedOperation(signal => new Promise((resolve,reject) => {const id=this.clock.setTimeout(resolve,ms);signal.addEventListener('abort',()=>{this.clock.clearTimeout(id);reject(signal.reason);},{once:true});}),ms+500,{signal:this.abort.signal,clock:this.clock});
  }
  resume(options = {}) {return this.run(options);}
  cancel() {this.abort?.abort(new RecoveryFault('cancelled','Recovery stopped.',{retryable:false}));}
  async finish(physicalConfirmed) {
    if(!physicalConfirmed || !this.verified.panel || this.state !== 'physical_confirmation') throw new RecoveryFault('physical_confirmation_required','Confirm the picture on the physical frame first.',{retryable:false});
    this.abort = new AbortController(); await this.op('end'); this.emit('finished','end'); try {this.storage?.removeItem(this.key);} catch {}
  }
}
