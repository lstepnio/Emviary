import {boundedOperation, RecoveryFault, defaultClock} from './recovery-controller.mjs';
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', {fatal:true});
export function crc32(bytes) { let crc = 0xffffffff; for(const byte of bytes) {crc ^= byte; for(let i=0;i<8;i++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));} return (crc ^ 0xffffffff) >>> 0; }
export function encodeRecoveryFrame(sequence, payload) {
  const json = JSON.stringify(payload), bytes = encoder.encode(json);
  if(bytes.length > 384 || !Number.isSafeInteger(sequence) || sequence < 1) throw new RecoveryFault('protocol_bounds','Recovery request exceeds protocol bounds.',{retryable:false});
  return encoder.encode(`!EMV1:${sequence}:${bytes.length}:${json}:${crc32(bytes).toString(16).padStart(8,'0')}\n`);
}
// Noise and ROM output are discarded. No unbounded line or reply queue is kept.
export class RecoveryFrameParser {
  constructor(onFrame, maxPayload = 1024) {this.onFrame = onFrame;this.maxPayload = maxPayload;this.buffer = [];this.discard = false;}
  push(bytes) {
    for(const byte of bytes) {
      if(byte === 10) {if(!this.discard) this.parse(new Uint8Array(this.buffer));this.buffer = [];this.discard=false;}
      else if(!this.discard) {this.buffer.push(byte);if(this.buffer.length > this.maxPayload + 96) {this.buffer=[];this.discard=true;}}
    }
  }
  parse(bytes) {
    try {
      const text = decoder.decode(bytes), match = /^!EMV1:(\d+):(\d+):/.exec(text);
      if(!match) return;
      const sequence = Number(match[1]), size = Number(match[2]), prefixBytes = encoder.encode(match[0]).length;
      if(!Number.isSafeInteger(sequence) || sequence < 1 || size > this.maxPayload) return;
      const json = bytes.slice(prefixBytes,prefixBytes+size), suffix = decoder.decode(bytes.slice(prefixBytes+size));
      if(!/^:[a-fA-F0-9]{8}\r?$/.test(suffix) || crc32(json) !== parseInt(suffix.slice(1),16)) return;
      const payload = JSON.parse(decoder.decode(json));
      if(!payload || typeof payload !== 'object' || Array.isArray(payload) || payload.protocol !== 1) return;
      this.onFrame({sequence,payload});
    } catch {} // Corrupt/truncated UART frames never become application evidence.
  }
}
export class RecoveryTransport {
  constructor(port,{clock = defaultClock,timeoutMs = 4000,onDisconnect = () => {}} = {}) {
    Object.assign(this,{port,clock,timeoutMs,onDisconnect});this.sequence=0;this.pending=null;this.reader=null;this.writer=null;this.closed=true;
    this.parser = new RecoveryFrameParser(frame => {if(this.pending?.sequence === frame.sequence) this.pending.resolve(frame.payload);});
  }
  async open({signal} = {}) {
    if(!this.closed) return;
    try {
      await boundedOperation(async openSignal => {await this.port.open({baudRate:115200}); if(openSignal.aborted) {try {await this.port.close();} catch {} throw openSignal.reason;}},this.timeoutMs,{signal,clock:this.clock,operation:'open'});
      this.closed=false;
      await boundedOperation(() => this.port.setSignals({dataTerminalReady:false,requestToSend:false}),this.timeoutMs,{signal,clock:this.clock,operation:'release_signals'});
      this.reader=this.port.readable.getReader();this.writer=this.port.writable.getWriter();this.reading=this.readLoop();
    } catch(error) {await this.close();throw error;}
  }
  async readLoop() {
    try {
      while(!this.closed) {const {value,done} = await this.reader.read();if(done) {if(!this.closed) throw new RecoveryFault('usb_disconnected','Reconnect the same frame to continue.',{retryable:false});break;} if(value) this.parser.push(value);}
    } catch(error) {
      if(!this.closed) {const fault = new RecoveryFault('usb_disconnected','Reconnect the same frame to continue.',{retryable:false});this.pending?.reject(fault);try {this.onDisconnect(fault);} catch {}}
    } finally {try {this.reader?.releaseLock();} catch {} this.reader=null;}
  }
  async command(cmd,fields = {},{signal,timeoutMs=this.timeoutMs} = {}) {
    if(this.closed) throw new RecoveryFault('usb_disconnected','USB is not open.',{retryable:false});
    if(this.pending) throw new RecoveryFault('protocol_busy','Another UART request is active.',{retryable:false});
    const sequence = ++this.sequence;
    let writeCompleted = false;
    try {
      return await boundedOperation(async requestSignal => {
        const reply = new Promise((resolve,reject) => {this.pending={sequence,resolve,reject};requestSignal.addEventListener('abort',()=>reject(requestSignal.reason),{once:true});});
        // Attach rejection handling before starting I/O, including timeout races.
        reply.catch(()=>{});
        await this.writer.write(encodeRecoveryFrame(sequence,{cmd,...fields}));
        writeCompleted = true;
        const result = await reply;
        if(['operation_busy','not_ready'].includes(result.error)) throw new RecoveryFault(result.error,result.error === 'operation_busy' ? 'The frame is completing another operation. Recovery will wait.' : 'The frame is still starting.',{retryable:true});
        if(result.error === 'session_mismatch' || result.error === 'session_conflict') throw new RecoveryFault(result.error,'Another or expired recovery session is active.',{retryable:false});
        if(cmd !== 'HELLO' && !(cmd === 'END_RECOVERY' && result.active === false && (!result.error || ['none','ok','ESP_OK'].includes(result.error))) && (result.session_id !== fields.session_id || result.nonce !== fields.nonce)) throw new RecoveryFault('session_mismatch','The UART reply belongs to another session.',{retryable:false});
        return result;
      },timeoutMs,{signal,clock:this.clock,operation:cmd});
    } catch(error) {
      // A pending write must be released on timeout. A completed, read-only
      // STATUS or HELLO request can leave its reader open and discard a late sequence.
      // Cancellation or a lost device always releases streams.
      const readonlyReplyTimeout = ['STATUS','HELLO'].includes(cmd) && writeCompleted && error.code === 'timeout' && !signal?.aborted;
      if(readonlyReplyTimeout) {error.replyTimeout=true;error.writeCompleted=true;}
      else if(error.code === 'timeout' || error.code === 'cancelled' || error.code === 'usb_disconnected' || signal?.aborted) await this.close();
      throw error;
    } finally {this.pending=null;}
  }
  async close() {
    this.closed=true;this.pending?.reject(new RecoveryFault('cancelled','UART closed.',{retryable:false}));
    if(this.reader) {try {await boundedOperation(()=>this.reader.cancel(),1000,{clock:this.clock,operation:'cancel_reader'});} catch {} }
    if(this.reading) {try {await boundedOperation(()=>this.reading,1000,{clock:this.clock,operation:'release_reader'});} catch {} this.reading=null;}
    if(this.writer) {try {await boundedOperation(()=>this.writer.abort(),1000,{clock:this.clock,operation:'abort_writer'});} catch {} try {this.writer.releaseLock();} catch {} this.writer=null;}
    try {await boundedOperation(()=>this.port.setSignals({dataTerminalReady:false,requestToSend:false}),1000,{clock:this.clock,operation:'release_signals'});} catch {}
    try {await boundedOperation(()=>this.port.close(),1000,{clock:this.clock,operation:'close_port'});} catch {}
    this.parser.buffer=[];this.parser.discard=false;
  }
}
