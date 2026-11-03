import test from 'node:test';
import assert from 'node:assert/strict';
import { inspectIndependentRivers } from '../src/recognition/sanmaAutoFrameObservation.js';

test('river branches overlap and preserve results', async () => {
  let release!: () => void;
  const barrier = new Promise<void>(resolve => { release = resolve; });
  let started = 0;
  const branch = (value: string) => async () => {
    if (++started === 2) release();
    await barrier;
    return value;
  };
  assert.deepEqual(await inspectIndependentRivers(branch('right'), branch('left')), ['right', 'left']);
});

test('one river failure does not erase the other branch', async () => {
  assert.deepEqual(await inspectIndependentRivers(async () => { throw new Error('right'); }, async () => 'left'), [undefined, 'left']);
  assert.deepEqual(await inspectIndependentRivers(async () => 'right', async () => { throw new Error('left'); }), ['right', undefined]);
  assert.deepEqual(await inspectIndependentRivers(() => { throw new Error('sync'); }, async () => 'left'), [undefined, 'left']);
});

test('shared classifier queues calls before worker timeout and continues after failure', async () => {
  const { serializeRiverClassifier } = await import('../src/recognition/sanmaAutoFrameObservation.js');
  let active = 0, maxActive = 0, calls = 0;
  let release!: () => void;
  const first = new Promise<void>(resolve => { release = resolve; });
  const classifier = serializeRiverClassifier({ backend: 'hybrid', async classifyTileImages() {
    const call = ++calls;
    maxActive = Math.max(maxActive, ++active);
    if (call === 1) await first;
    --active;
    if (call === 1) throw new Error('failed inference');
    return [];
  }});
  const a = classifier.classifyTileImages([]).catch(() => 'failed');
  const b = classifier.classifyTileImages([]);
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(calls, 1);
  release();
  assert.equal(await a, 'failed');
  assert.deepEqual(await b, []);
  assert.equal(maxActive, 1);
  assert.equal(classifier.backend, 'hybrid');
});

test('three callers keep FIFO after synchronous and asynchronous worker failures', async () => {
  const { serializeRiverClassifier } = await import('../src/recognition/sanmaAutoFrameObservation.js');
  const order: number[] = [];
  let active=0, maxActive=0;
  const classifier = serializeRiverClassifier({ classifyTileImages(images) {
    const id=images[0]?.[0];
    if(id === undefined) throw new Error('missing call identifier');
    order.push(id); maxActive=Math.max(maxActive,++active);
    if(id===1) {active--; throw new Error('sync failure');}
    return Promise.resolve().then(() => {
      active--;
      if(id===2) throw new Error('async failure');
      return [];
    });
  }});
  const a=classifier.classifyTileImages([Buffer.from([1])]);
  const b=classifier.classifyTileImages([Buffer.from([2])]);
  const c=classifier.classifyTileImages([Buffer.from([3])]);
  const results=await Promise.allSettled([a,b,c]);
  assert.deepEqual(order,[1,2,3]); assert.equal(maxActive,1);
  assert.deepEqual(results.map(x=>x.status),['rejected','rejected','fulfilled']);
});
