// Process-local diagnostics only; never restart a browser or touch a game page.
export function watchBrowserLifecycle(context, processEvents, write = (line) => process.stderr.write(line)) {
  let signal = null;
  const emit = (event, extra = {}) => write(`${JSON.stringify({time: new Date().toISOString(), event, pid: processEvents.pid, ...extra})}\n`);
  const onClose = () => emit('browser_context_closed', {signal});
  const onExit = (code) => emit('launcher_exit', {code, signal});
  const recordSignal = (name) => { signal ??= name; emit('launcher_signal', {signal: name}); };
  context.on('close', onClose);
  processEvents.on('exit', onExit);
  emit('browser_context_started');
  return {recordSignal, unwatch: () => {
    context.off('close', onClose);
    processEvents.off('exit', onExit);
  }};
}
