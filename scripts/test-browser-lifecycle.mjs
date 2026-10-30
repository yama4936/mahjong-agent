import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { test } from 'node:test';
import { watchBrowserLifecycle } from './browser-lifecycle.mjs';

test('records clean signal and lifecycle without taking browser action', () => {
  const context = new EventEmitter();
  const processEvents = new EventEmitter();
  processEvents.pid = 123;
  const records = [];
  const lifecycle = watchBrowserLifecycle(context, processEvents, (line) => records.push(JSON.parse(line)));
  lifecycle.recordSignal('SIGTERM');
  context.emit('close');
  processEvents.emit('exit', 0);
  assert.deepEqual(records.map((r) => r.event), ['browser_context_started', 'launcher_signal', 'browser_context_closed', 'launcher_exit']);
  assert.equal(records[2].signal, 'SIGTERM');
  assert.equal(records[3].code, 0);
  assert.ok(records.every((r) => r.pid === 123 && !Number.isNaN(Date.parse(r.time))));
  lifecycle.unwatch();
  assert.equal(context.listenerCount('close'), 0);
});

test('unexpected browser close remains unknown rather than guessing a cause', () => {
  const context = new EventEmitter();
  const processEvents = new EventEmitter();
  processEvents.pid = 123;
  const records = [];
  watchBrowserLifecycle(context, processEvents, (line) => records.push(JSON.parse(line)));
  context.emit('close');
  assert.equal(records[1].event, 'browser_context_closed');
  assert.equal(records[1].signal, null);
});

test('real SIGTERM and SIGINT preserve default and existing handler exit behavior', async () => {
  const {spawn} = await import('node:child_process');
  const moduleUrl = new URL('./browser-lifecycle.mjs', import.meta.url).href;
  for (const signal of ['SIGTERM', 'SIGINT']) {
    for (const handled of [false, true]) {
      const source = `import {EventEmitter} from 'node:events';
        import {watchBrowserLifecycle} from ${JSON.stringify(moduleUrl)};
        const ctx = new EventEmitter();
        const lifecycle = watchBrowserLifecycle(ctx, process);
        if (${handled}) process.once(${JSON.stringify(signal)}, () => {
          lifecycle.recordSignal(${JSON.stringify(signal)}); ctx.emit('close'); process.exit(0);
        });
        process.stdout.write('ready\\n'); setInterval(() => {}, 1000);`;
      const child = spawn(process.execPath, ['--input-type=module', '-e', source], {stdio: ['ignore', 'pipe', 'pipe']});
      let stderr = '';
      child.stderr.setEncoding('utf8').on('data', (chunk) => { stderr += chunk; });
      await new Promise((resolve, reject) => { child.stdout.once('data', resolve); child.once('error', reject); });
      const exited = new Promise((resolve) => child.once('exit', (code, bySignal) => resolve({code, bySignal})));
      child.kill(signal);
      const result = await exited;
      assert.deepEqual(result, handled ? {code: 0, bySignal: null} : {code: null, bySignal: signal});
      if (handled) assert.match(stderr, new RegExp(`"signal":"${signal}"`));
    }
  }
});
