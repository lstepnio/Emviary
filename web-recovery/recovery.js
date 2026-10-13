import {ESPLoader,Transport} from 'esptool-js';
import SparkMD5 from 'spark-md5';
import {loadRecovery,repairRecoveryRegions,restoreRecoverySettings,cloudSettingsFile,recoveryPort,RecoveryTargetError,transferProgress} from './recovery-core.mjs';
import {RecoveryController,RecoveryFault,boundedOperation} from './recovery-controller.mjs';
import {RecoveryTransport} from './recovery-transport.mjs';
import {renderRecovery} from './recovery-ui.mjs';
const panel=document.querySelector('[data-usb-recovery]');
if(panel) {
  const frame=panel.dataset.frame,start=panel.querySelector('[data-usb-start]'),
    next=panel.querySelector('[data-usb-wake]'),fresh=panel.querySelector('[data-usb-cloud]'),
    cancel=panel.querySelector('[data-usb-cancel]'),progress=panel.querySelector('progress');
  const supported=window.isSecureContext&&'serial' in navigator;
  const base='/manage/usb-recovery/sessions/'+encodeURIComponent(frame);
  const journalKey='emviary-recovery-session:'+frame;
  const settingsAttemptKey=sessionId=>'emviary-recovery-settings-attempt:'+sessionId;
  let bundle,metadata,job,controller,port,uart,busy=false,preparing=false,criticalWriting=false,automaticSettingsAttempted=false,displayTestUsed=false,renewTimer,csrf,releaseLock,runAbort,cancelRequested=false;
  const md5=data=>SparkMD5.ArrayBuffer.hash(data.buffer.slice(data.byteOffset,data.byteOffset+data.byteLength));
  const digest=crypto.subtle.digest.bind(crypto.subtle);
  const display=event=>renderRecovery(panel,event);
  const update=()=>{
    start.disabled=!supported||preparing||busy;
    next.disabled=!supported||preparing||busy;cancel.hidden=!busy||criticalWriting||controller?.state==='repairing';
    panel.querySelector('[data-usb-intro]').hidden=busy||!!controller;
    [...fresh.elements].forEach(input=>input.disabled=!supported||busy);
    panel.setAttribute('aria-busy',String(busy));
  };
  const request=async(url,options={})=>{
    const {response,payload}=await boundedOperation(async signal=>{const response=await fetch(url,{cache:'no-store',...options,signal});return {response,payload:await response.json()};},10000,{signal:options.signal,operation:'web_request'});
    if(!response.ok){
      const detail=payload.detail;
      const code=typeof detail==='object'&&typeof detail?.code==='string'?detail.code:
        response.status===409?'tab_conflict':[401,403].includes(response.status)?'authentication':response.status===400&&url.includes('/cloud-settings/')?'configuration_required':'service_error';
      const message=typeof detail==='string'?detail:typeof detail?.message==='string'?detail.message:'Emviary could not complete this step.';
      const error=new RecoveryFault(code,message,{retryable:response.status>=500});error.status=response.status;throw error;
    }
    return payload;
  };
  const post=async(url,fields={},signal)=>{
    signal ||= runAbort?.signal;
    if(!csrf)csrf=(await request('/manage/session',{signal})).csrf;
    return request(url,{method:'POST',body:new URLSearchParams({csrf,...fields}),signal});
  };
  const close=async()=>{if(uart){await uart.close();uart=null;}};
  const openUart=async signal=>{if(!uart){uart=new RecoveryTransport(port);await uart.open({signal});}return uart;};
  const reset=async signal=>{
    await close();const link=await openUart(signal);
    const check=()=>{if(signal?.aborted)throw signal.reason;};
    try{
      check();await link.port.setSignals({dataTerminalReady:false,requestToSend:true});
      await new Promise(resolve=>setTimeout(resolve,120));
      check();
    }finally{await link.port.setSignals({dataTerminalReady:false,requestToSend:false});}
    // Keep the reader and port open through reset. Closing the bridge here can
    // change its control lines and lose both boot output and the first reply.
    await new Promise(resolve=>setTimeout(resolve,350));check();
  };
  const openLoader=()=>{
    const transport=new Transport(port,false);
    const loader=new ESPLoader({transport,baudrate:115200,debugLogging:false,
      terminal:{clean(){},write(){},writeLine(){}}});return {loader,transport};
  };
  const identify=async({signal})=>{
    await close();const {loader,transport}=openLoader();
    const stop=()=>transport.disconnect().catch(()=>{});signal.addEventListener('abort',stop,{once:true});
    const write=transport.write.bind(transport);transport.write=async(...args)=>{if(signal.aborted)throw signal.reason;return write(...args);};
    try{
      await loader.main('default_reset');
      if(signal.aborted)throw signal.reason;
      if(loader.chip?.CHIP_NAME!=='ESP32-S3'||await loader.detectFlashSize()!=='32MB'||loader.secureDownloadMode)throw new RecoveryFault('wrong_board','This device does not match the E1002.',{retryable:false});
      const security=await loader.getSecurityInfo();
      if(security.parsedFlags.SECURE_BOOT_EN||security.flashCryptCnt!==0)throw new RecoveryFault('unsupported_security','This protected device needs its original recovery method.',{retryable:false});
      return {device_identity:(await loader.chip.readMac(loader)).replace(/:/g,'').toLowerCase(),board:'seeedstudio_reterminal_e1002'};
    }finally{signal.removeEventListener('abort',stop);await transport.disconnect().catch(()=>{});}
  };
  const reportWrite=(index,written,total)=>{
    progress.hidden=false;progress.value=transferProgress(bundle.files,index,written,total);
    const label=panel.querySelector('[data-usb-progress-label]');if(label){label.hidden=false;label.textContent=Math.round(progress.value)+'% of software written';}
  };
  const onEvent=event=>{
    display(event);update();
    if(event.state!=='repairing'){progress.hidden=true;const label=panel.querySelector('[data-usb-progress-label]');if(label)label.hidden=true;}
    const attention=['needs_attention','paused','cancelled'].includes(event.state);
    panel.querySelector('[data-usb-wake-panel]').hidden=!attention;
    if(attention){start.hidden=true;next.textContent=event.state==='paused'?'Continue after reconnecting':'Continue recovery';}
    const settings=event.state==='needs_attention'&&(event.error?.code==='configuration_required'||event.error?.code==='wifi_connection_failed'||event.error?.code==='network_timeout'||event.error?.code==='wifi_password_required'||String(event.error?.code||'').includes('NVS'));
    fresh.hidden=!settings;
    if(event.state==='physical_confirmation'){
      const preview=panel.querySelector('[data-usb-preview]');if(preview&&event.evidence?.image_id){preview.src='/manage/images/'+event.evidence.image_id+'/preview';preview.hidden=false;}
      start.hidden=true;panel.querySelector('[data-usb-finish]').hidden=false;
    }
    if(event.state==='finished'){
      panel.querySelector('[data-usb-finish]').hidden=true;
      panel.querySelector('[data-usb-wake-panel]').hidden=true;
    }
    if(job&&event.operation&&event.operation!=='status')post(base+'/'+job.session_id+'/events',{
      attempt_id:String(event.attempt_id),state:event.state,operation:event.operation,
      elapsed_ms:String(Math.round(event.elapsed_ms)),...(event.error?{error:event.error.code}:{})
    }).catch(()=>{});
  };
  const operations={
    prepare:async()=>bundle,
    hello:async({signal})=>(await openUart(signal)).command('HELLO',{}, {signal}),
    identify,
    reset:async({signal})=>reset(signal),
    repair:async({signal,baud})=>{
      await close();const transport=new Transport(port,false);
      const loader=new ESPLoader({transport,baudrate:baud,debugLogging:false,terminal:{clean(){},write(){},writeLine(){}}});
      try{return await repairRecoveryRegions(loader,transport,bundle.files,md5,reportWrite,{signal,expectedIdentity:controller.identity});}
      catch(error){if(error instanceof RecoveryTargetError)throw new RecoveryFault('wrong_board',error.message,{retryable:false});throw error;}
    },
    verifyFirmware:async({signal})=>{
      await close();const {loader,transport}=openLoader();
      const stop=()=>transport.disconnect().catch(()=>{});signal.addEventListener('abort',stop,{once:true});
      const write=transport.write.bind(transport);transport.write=async(...args)=>{if(signal.aborted)throw signal.reason;return write(...args);};
      try{if(signal.aborted)throw signal.reason;await loader.main('default_reset');for(const file of bundle.files){if(signal.aborted)throw signal.reason;const hash=await loader.flashMd5sum(file.address,file.data.length);if(signal.aborted)throw signal.reason;if(hash!==md5(file.data))return false;}return true;}
      finally{signal.removeEventListener('abort',stop);await transport.disconnect().catch(()=>{});}
    },
    begin:async({signal,sessionId,nonce})=>(await openUart(signal)).command('BEGIN_RECOVERY',{session_id:sessionId,nonce,bundle_sha256:job.bundle_sha256},{signal}),
    status:async({signal,sessionId,nonce})=>(await openUart(signal)).command('STATUS',{session_id:sessionId,nonce},{signal}),
    cloud:async({signal,bootId,imageSha256})=>{
      const result=await request(base+'/'+job.session_id,{signal});
      if(result.boot_id!==bootId||result.expected_firmware!==bundle.manifest.version||result.device_id!==controller.identity||!result.evidence?.panel_refreshed||!result.evidence?.image_verified||imageSha256&&result.image_sha256!==imageSha256)throw new RecoveryFault('cloud_unverified','Emviary has not confirmed this boot and picture.',{retryable:false});
      return {session_verified:true,connected:true,image_sha256:result.image_sha256,image_id:result.image_id};
    },
    end:async({signal,sessionId,nonce})=>{
      try{const link=await openUart(signal);const hello=await link.command('HELLO',{}, {signal});controller.checkBoot(hello);if(hello.active)await link.command('END_RECOVERY',{session_id:sessionId,nonce},{signal});}finally{await close();}
      await post(base+'/'+sessionId+'/complete',{physical_confirmed:'yes'},signal);
      clearInterval(renewTimer);try{sessionStorage.removeItem(journalKey);sessionStorage.removeItem(settingsAttemptKey(sessionId));}catch{}
    },
    release:async()=>close(),
  };
  const session=async()=>{
    if(job&&job.state==='active'){job=await post(base+'/'+job.session_id+'/renew');return job;}
    let stored;try{stored=JSON.parse(sessionStorage.getItem(journalKey));}catch{}
    if(stored){try{const found=await request(base+'/'+stored.session_id);if(found.state==='active'&&found.expected_firmware===bundle.manifest.version){job=await post(base+'/'+found.session_id+'/renew');return job;}}catch(error){if(error.code==='authentication')throw error;}}
    job=await post(base);try{sessionStorage.setItem(journalKey,JSON.stringify({session_id:job.session_id}));}catch{}return job;
  };
  const execute=async selected=>{
    if(busy)return;port=selected;busy=true;cancelRequested=false;runAbort=new AbortController();start.hidden=true;update();
    panel.querySelector('[data-usb-finish]').hidden=true;
    try{
      if(navigator.locks)await new Promise((resolve,reject)=>{
        navigator.locks.request('emviary-recovery:'+frame,{ifAvailable:true},async lock=>{
          if(!lock){reject(new RecoveryFault('tab_conflict','Recovery is open in another tab.',{retryable:false}));return;}
          await new Promise(done=>{releaseLock=done;resolve();});
        }).catch(reject);
      });
      await session();
      try{automaticSettingsAttempted=sessionStorage.getItem(settingsAttemptKey(job.session_id))==='yes';}catch{}
      if(controller&&(controller.sessionId!==job.session_id||controller.nonce!==job.nonce))controller=null;
      if(runAbort.signal.aborted)throw new RecoveryFault('cancelled','Recovery stopped.');
      clearInterval(renewTimer);renewTimer=setInterval(()=>post(base+'/'+job.session_id+'/renew').catch(()=>{}),30000);
      if(!controller)controller=new RecoveryController({frameId:frame,expectedIdentity:job.device_id||undefined,
        expectedFirmware:bundle.manifest.version,sessionId:job.session_id,nonce:job.nonce,
        operations,onEvent,storage:sessionStorage,deadlines:{repair:360000,hello:8000}});
      await controller.run({port,repair:true});
    }catch(error){
      const settingsFailure=['configuration_required'].includes(error.code)||String(error.code||'').includes('NVS');
      if(!cancelRequested&&!automaticSettingsAttempted&&settingsFailure&&metadata?.can_restore_without_input&&metadata?.automatic_restore_ssid&&controller?.state==='needs_attention'){
        automaticSettingsAttempted=true;
        try{sessionStorage.setItem(settingsAttemptKey(job.session_id),'yes');}catch{}
        try{await restoreSettings({ssid:metadata.automatic_restore_ssid,replace_local_settings:'yes'},{automatic:true});await controller.run({port,repair:true});}
        catch(restorationError){if(!cancelRequested)onEvent({state:'needs_attention',error:{code:restorationError.code||'configuration_required',message:restorationError.message}});}
      }
      else if(!cancelRequested&&error.code!=='cancelled'&&(!controller||controller.state!=='needs_attention'&&controller.state!=='paused'&&controller.state!=='cancelled'))onEvent({state:'needs_attention',error:{code:error.code||'operation_failed',message:error.message}});}
    finally{busy=false;releaseLock?.();releaseLock=null;update();}
  };
  const choose=async()=>{
    if(busy||preparing||!supported)return;
    try{display({state:'identifying'});port=await recoveryPort(navigator.serial,port);if(!bundle)await prepare();if(!bundle)return;await execute(port);}
    catch(error){onEvent({state:'needs_attention',error:{code:error.name==='NotFoundError'?'permission_cancelled':error.code||'port_busy',message:error.message}});}
  };
  start.textContent='Check and recover';
  start.addEventListener('click',choose);next.addEventListener('click',choose);
  cancel.addEventListener('click',async()=>{
    cancelRequested=true;runAbort?.abort();controller?.cancel();clearInterval(renewTimer);
    if(job)await post(base+'/'+job.session_id+'/cancel',{},AbortSignal.timeout(5000)).catch(()=>{});
    try{if(job)sessionStorage.removeItem(settingsAttemptKey(job.session_id));sessionStorage.removeItem(journalKey);}catch{}
    job=null;controller=null;onEvent({state:'cancelled'});
  });
  navigator.serial?.addEventListener('connect',async()=>{if(controller?.state==='paused'&&!busy)try{const ports=await navigator.serial.getPorts();if(ports.includes(port))await execute(port);}catch{}});
  panel.querySelector('[data-usb-good]').addEventListener('click',async()=>{
    if(busy||!controller)return;busy=true;update();
    try{await controller.finish(true);}catch(error){onEvent({state:'needs_attention',error:{code:error.code||'operation_failed',message:error.message}});}
    finally{busy=false;update();}
  });
  const restoreSettings=async(fields,{automatic=false}={})=>{
    let nvs;criticalWriting=true;update();
    try{
      const payload=await post('/manage/usb-recovery/cloud-settings/'+encodeURIComponent(frame),{...fields,session_id:job.session_id,replace_local_settings:'yes'});
      nvs=await cloudSettingsFile(payload,frame,digest);await close();
      const transport=new Transport(port,false),loader=new ESPLoader({transport,baudrate:115200,debugLogging:false,terminal:{clean(){},write(){},writeLine(){}}});
      display({state:'repairing_settings'});
      await boundedOperation(signal=>restoreRecoverySettings(loader,transport,nvs,md5,(_i,w,t)=>{progress.hidden=false;progress.value=Math.min(99,w/t*100);},{signal,expectedIdentity:controller.identity,consent:true}),60000,{operation:'restore_settings',signal:runAbort?.signal});
      fresh.querySelector('[name="password"]').value='';
      const access=panel.querySelector('[data-usb-local-password]');if(access&&payload.local_password&&!automatic)access.textContent=payload.local_password;
      await reset(runAbort?.signal);
    }finally{nvs?.data.fill(0);criticalWriting=false;update();}
  };
  fresh.addEventListener('submit',async event=>{
    event.preventDefault();event.stopPropagation();if(busy||!supported||!job||!fresh.querySelector('[name="replace_local_settings"]').checked)return;
    busy=true;cancelRequested=false;runAbort=new AbortController();update();let restored=false;
    try{
      const fields=Object.fromEntries([...fresh.elements].filter(input=>input.name&&input.type!=='submit'&&(input.type!=='checkbox'||input.checked)).map(input=>[input.name,input.value]));
      await restoreSettings(fields);restored=true;
    }catch(error){if(!cancelRequested)onEvent({state:'needs_attention',error:{code:error.code||'configuration_required',message:error.message}});}
    finally{busy=false;update();}
    if(restored)await execute(port);
  });
  panel.querySelector('[data-usb-not-yet]').addEventListener('click',async()=>{
    if(busy||!controller||controller.state!=='physical_confirmation')return;
    if(displayTestUsed){controller.verified.panel=false;controller.state='needs_attention';panel.querySelector('[data-usb-finish]').hidden=true;onEvent({state:'needs_attention',error:{code:'display_failed',message:'The display test has already run. Keep USB connected for display support.'}});return;}
    displayTestUsed=true;controller.verified.panel=false;controller.state='display_test';panel.querySelector('[data-usb-finish]').hidden=true;busy=true;runAbort=new AbortController();update();
    try{
      await boundedOperation(async signal=>{
        const link=await openUart(signal);const hello=await link.command('HELLO',{}, {signal});controller.checkBoot(hello);
        if(hello.boot_id!==controller.verified.boot)throw new RecoveryFault('boot_changed','The frame restarted. Continue recovery to verify its new boot before checking the display.',{retryable:false});
        let prepared=await link.command('BEGIN_RECOVERY',{session_id:job.session_id,nonce:job.nonce,bundle_sha256:job.bundle_sha256},{signal});
        while(prepared.panel!=='complete'){
          if(prepared.error&&!['none','ok','ESP_OK'].includes(prepared.error)||['error'].includes(prepared.image)||['error'].includes(prepared.panel))throw new RecoveryFault('display_failed','The frame needs its picture pipeline verified before the display test.',{retryable:false});
          display({state:'display_prepare'});
          await new Promise(resolve=>setTimeout(resolve,1500));if(signal.aborted)throw signal.reason;
          prepared=await link.command('STATUS',{session_id:job.session_id,nonce:job.nonce},{signal});controller.checkBoot(prepared);
          if(prepared.boot_id!==controller.verified.boot)throw new RecoveryFault('boot_changed','The frame restarted. Continue recovery before checking the display.',{retryable:false});
        }
        display({state:'display_test'});
        let status=await link.command('DISPLAY_TEST',{session_id:job.session_id,nonce:job.nonce},{signal});
        while(status.test_pattern==='pending'||status.test_pattern==='idle'){
          await new Promise(resolve=>setTimeout(resolve,1500));if(signal.aborted)throw signal.reason;
          status=await link.command('STATUS',{session_id:job.session_id,nonce:job.nonce},{signal});
        }
        if(status.test_pattern!=='complete')throw new RecoveryFault('display_failed','The frame could not complete its display test.',{retryable:false});
        display({state:'restoring_picture'});
        status=await link.command('RESTORE_PICTURE',{session_id:job.session_id,nonce:job.nonce},{signal});
        while(status.test_pattern!=='restored'&&status.test_pattern!=='error'){
          await new Promise(resolve=>setTimeout(resolve,1500));if(signal.aborted)throw signal.reason;
          status=await link.command('STATUS',{session_id:job.session_id,nonce:job.nonce},{signal});
        }
        if(status.test_pattern!=='restored')throw new RecoveryFault('display_failed','The frame could not restore its saved picture.',{retryable:false});
      },150000,{signal:runAbort.signal,operation:'display_check'});
      controller.verified.panel=true;controller.state='physical_confirmation';
      onEvent({state:'physical_confirmation',evidence:{image_id:controller.verified.cloud?job.image_id:undefined}});
      panel.querySelector('[data-usb-status]').textContent='The display test completed and your saved picture was restored. Does the picture appear and stay visible on your frame?';
    }catch(error){if(controller){controller.verified.panel=false;controller.state='needs_attention';}if(!cancelRequested)onEvent({state:'needs_attention',error:{code:error.code||'display_failed',message:error.message}});}
    finally{await close();busy=false;update();}
  });
  window.addEventListener('beforeunload',event=>{if(busy&&(criticalWriting||controller?.state==='repairing')){event.preventDefault();event.returnValue='';}});
  const prepare=async()=>{
    if(preparing||!supported)return;preparing=true;display({state:'preparing'});update();
    try{
      for(let attempt=0;attempt<3;attempt++){
        try{
          const [ready,details]=await boundedOperation(signal=>Promise.all([
            loadRecovery((url,options={})=>requestDownload(url,{...options,signal}),digest,location.origin),
            request('/manage/usb-recovery/status/'+encodeURIComponent(frame),{signal}),
          ]),30000,{operation:'prepare'});
          bundle=ready;metadata=details;
          const options=panel.querySelector('[data-usb-networks]');
          [...new Set([metadata.suggested_network,...(metadata.network_names||[])].filter(Boolean))].forEach(name=>{const option=document.createElement('option');option.value=name;options?.append(option);});
          fresh.querySelector('[name="ssid"]').value=metadata.suggested_network||metadata.network_names?.[0]||'';
          display({state:'idle'});return;
        }catch(error){if(error.code==='authentication'||error.status&&error.status<500||attempt===2)throw error;display({state:'preparing',operation:'retry_prepare'});await new Promise(resolve=>setTimeout(resolve,(attempt+1)*1000));}
      }
    }catch(error){onEvent({state:'needs_attention',error:{code:error.code||'service_error',message:error.message}});}
    finally{preparing=false;update();}
  };
  const requestDownload=async(url,options)=>{
    const response=await fetch(url,{cache:'no-store',...options});
    if(!response.ok){const error=new RecoveryFault([401,403].includes(response.status)?'authentication':'service_error','Recovery files could not be downloaded.',{retryable:response.status>=500});error.status=response.status;throw error;}
    return response;
  };
  if(!supported){onEvent({state:'needs_attention',error:{code:'unsupported_browser',message:'Use Chrome or Edge on a laptop.'}});update();}
  else prepare();
}
