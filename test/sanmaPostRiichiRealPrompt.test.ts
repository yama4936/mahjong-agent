import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import sharp from 'sharp';
import { EXPERIMENTAL_BUTTONS, type ExperimentalTemplates } from '../src/recognition/sanmaButtonExperiment.js';
import { inspectSanmaButtonRow } from '../src/recognition/sanmaButtonRowExperiment.js';

const ron = '/home/yama1/.codex/sanma-run-1740066-20261031/manual-20-before.png';
const kita = '/home/yama1/.codex/sanma-run-0bf97c7-20261101/manual-13-immediate.png';
const tsumo = '/home/yama1/.codex/sanma-run-0bf97c7-20261101/manual-14-before.png';

test('real post-riichi friend prompts: identify buttons without granting operation', {skip: ![ron,kita,tsumo].every(existsSync)}, async () => {
 const templates = Object.fromEntries(await Promise.all(EXPERIMENTAL_BUTTONS.map(async name => [name, await readFile(`test/fixtures/sanma-buttons/${name}.png`)]))) as ExperimentalTemplates;
 const skip = await sharp(await readFile('test/fixtures/sanma-button-rows/kita.png')).extract({left:580,top:0,width:245,height:90}).png().toBuffer();
 const empty = await readFile('test/fixtures/sanma-button-rows/empty.png');
 const ronRef = await sharp(await readFile('test/fixtures/ron-button-rows/ron1.png')).extract({left:290,top:0,width:245,height:90}).png().toBuffer();
 for (const [file,expected] of ([[ron,'ron'],[kita,'kita'],[tsumo,'tsumo']] as const)) {
  const row = await sharp(await readFile(file)).extract({left:600,top:785,width:825,height:90}).png().toBuffer();
  const result = await inspectSanmaButtonRow(row,templates,skip,empty,ronRef);
  assert.equal(result.slots[1]?.status, 'candidate');
  if (result.slots[1]?.status === 'candidate') assert.equal(result.slots[1].action, expected);
  assert.equal(result.ronReferenceCompared, true);
  assert.equal(result.operationAuthorized, false);
  if (expected === 'ron') {
   const noRonReference = await inspectSanmaButtonRow(row, templates, skip, empty);
   assert.equal(noRonReference.slots[1]?.status, 'unresolved');
   const ambiguous = await inspectSanmaButtonRow(row, {...templates, tsumo: ronRef}, skip, empty, ronRef);
   assert.equal(ambiguous.slots[1]?.status, 'unresolved');
  }
 }
});
