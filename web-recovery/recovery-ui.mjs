const steps = {preparing:'prepare',identifying:'prepare',identified:'prepare',repairing:'restore',
  firmware_verified:'restore',booting:'connect',application_booted:'connect',connecting:'connect',
  physical_confirmation:'finish',finished:'finish',application_busy:'connect',repairing_settings:'restore',display_prepare:'finish',display_test:'finish',restoring_picture:'finish'};
const copy = {
  idle:['Connect your frame','Plug in a USB data cable and turn the power switch on. We’ll guide you from here.'],
  preparing:['Getting everything ready','Checking the recovery files and your saved settings.'],
  application_busy:['Waiting for your frame','Your frame is finishing another operation. Recovery will continue when it is ready.'],
  repairing_settings:['Restoring saved settings','Restoring this frame’s cloud settings and saved Wi-Fi. Keep USB connected.'],
  display_prepare:['Getting the display check ready','Waiting for the current picture to finish before running one display test.'],
  display_test:['Checking the display','Running one display test. Your saved picture will be restored afterwards.'],
  restoring_picture:['Restoring your picture','The display test finished. Restoring the saved picture before your final check.'],
  identifying:['Finding your frame','Checking the USB connection. Keep the cable connected.'],
  identified:['Frame found','Checking what needs restoring. Your saved settings are kept.'],
  repairing:['Restoring your frame','Installing and checking the recovery software. Keep USB connected and leave the buttons untouched.'],
  firmware_verified:['Software restored','The files have been checked. Next, we’ll start your frame.'],
  booting:['Starting your frame','Waiting for the frame to start. No button press is needed.'],
  application_booted:['Your frame has started','Connecting using its saved Wi-Fi settings.'],
  connecting:['Reconnecting your frame','Waiting for your frame to connect and request its picture. Keep USB connected.'],
  physical_confirmation:['Check your picture','Your frame completed its picture refresh. Compare its display with the picture below.'],
  finished:['Your frame is ready','You can unplug USB. Your frame will follow its saved schedule.'],
  paused:['USB disconnected','Reconnect the same frame. Recovery will continue from its last verified step.'],
  cancelled:['Checking stopped','Completed repairs are kept. Choose Continue recovery when you’re ready.'],
};
export function recoveryCopy(event) {
  const state=event.state || 'idle'; let [title,message]=copy[state] || ['Let’s finish recovery','Keep USB connected.'];
  if(state==='connecting') {
    const e=event.evidence || {};
    if(event.operation==='retry_pipeline') [title,message]=['Trying the connection again','Retrying the picture and connection check. Completed repairs and your saved settings are kept.'];
    else
    if(e.image==='verified' && e.panel!=='complete') [title,message]=['Refreshing your picture','The picture is downloaded. The color display needs a little time to finish.'];
    else if(e.wifi_connected) [title,message]=['Getting your picture','Wi-Fi is connected. Waiting for a verified picture refresh.'];
  }
  if(state==='needs_attention') {
    const code=event.error?.code;
    [title,message]= {
      unsupported_browser:['Open recovery on a laptop','Use Chrome or Edge on a laptop to connect your frame over USB.'],
      unsupported_security:['This frame uses protected software','Use the recovery method supplied with its protected firmware. Nothing was written.'],
      operation_busy:['Your frame is finishing another operation','Give it a moment, then choose Continue recovery.'],
      not_ready:['Your frame is still starting','Keep USB connected, then continue once startup finishes.'],
      wifi_password_required:['Confirm your Wi-Fi password',event.error?.message||'Enter the password for this network below.'],
      wifi_connection_failed:['Let’s reconnect to Wi-Fi','The saved Wi-Fi could not connect after several attempts. Confirm its network and password below.'],
      image_failed:['The picture could not be downloaded','Your software and settings are kept. Continue when Emviary can provide the picture.'],
      cloud_failed:['Emviary could not be reached','Your software and settings are kept. Check Emviary or your network, then continue.'],
      service_error:['Emviary is temporarily unavailable','Your completed repairs are kept. Continue when the service is available again.'],
      storage_failed:['The frame’s picture storage needs attention','Keep USB connected and use the frame’s storage diagnostics. Wi-Fi settings are kept.'],
      initialization_failed:['Your frame could not finish starting','Keep USB connected and check the startup details below.'],
      display_failed:['The display needs attention','The display did not complete its check. Keep USB connected for display support; your settings are kept.'],
      port_busy:['USB is being used','Close other recovery tabs or serial apps, then continue.'],
      permission_cancelled:['Choose your frame','Select USB Serial in the browser’s picker, then click Connect.'],
      wrong_device:['This is a different device','Connect the frame selected on this page. Nothing was written to the different device.'],
      wrong_board:['Check the connected frame','This recovery is for the reTerminal E1002. Connect that frame to continue.'],
      boot_changed:['Your frame restarted','Choose Continue recovery to verify its new startup before checking the display.'],
      boot_unverified:['The frame hasn’t started yet','Keep the power switch on and USB connected. We need to confirm the frame starts before continuing.'],
      configuration_required:['Let’s reconnect to Wi-Fi','The saved settings need attention. Restore this frame’s cloud settings below.'],
      network_timeout:['Your frame needs help connecting','Check that its saved Wi-Fi is available. Continue to try again, or update its Wi-Fi below if needed.'],
      cloud_unverified:['Waiting for Emviary','Your frame has progressed, but Emviary hasn’t confirmed this session. Keep USB connected and try again shortly.'],
      authentication:['Sign in to continue','Your management session expired. Sign in again, then return here to continue.'],
      tab_conflict:['Recovery is open elsewhere','Finish or stop recovery in the other tab, then continue here.'],
    }[code] || ['Recovery needs your help','We couldn’t finish this step. Keep USB connected, then choose Continue recovery. Details are available below.'];
  }
  return {state,title,message,step:steps[state],attention:state==='needs_attention'||state==='paused',complete:state==='finished'};
}
export function renderRecovery(panel,event) {
  const view=recoveryCopy(event);
  panel.dataset.recoveryState=view.state;
  const write=(selector,text)=>{const node=panel.querySelector(selector);if(node)node.textContent=text;};
  write('[data-usb-heading]',view.title);write('[data-usb-status]',view.message);
  write('[data-usb-orb]',view.complete?'✓':view.attention?'!':view.state==='idle'?'↗':'↻');
  const order=['prepare','restore','connect','finish'];
  panel.querySelectorAll('[data-usb-step]').forEach(node=>{
    const active=node.dataset.usbStep===view.step;
    if(active)node.setAttribute('aria-current','step');else node.removeAttribute('aria-current');
    node.dataset.complete=String(view.complete || order.indexOf(node.dataset.usbStep)<order.indexOf(view.step));
  });
  write('[data-usb-debug]',[event.operation,event.error?.code,
    event.error?.message, Number.isFinite(event.elapsed_ms)?Math.floor(event.elapsed_ms/1000)+' seconds elapsed':null].filter(Boolean).join(' · '));
  return view;
}
