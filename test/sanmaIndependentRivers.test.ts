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
