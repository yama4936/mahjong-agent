// Explicit installation, performed between matches. Existing matches must not
// have their templates changed while the recognition process is running.
import { constants } from 'node:fs';
import { copyFile, readFile } from 'node:fs/promises';
import sharp from 'sharp';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const destination = process.argv[2] ? path.resolve(process.argv[2]) : path.join(root, 'templates/bootstrap');
// Verify the 34 pinned bootstrap base files are readable images. This is a
// completeness check only; it does not certify template identity or accuracy.
const classes = ['m','p','s'].flatMap(suit => Array.from({length:9}, (_, i) => `${i+1}${suit}`))
  .concat(['E','S','W','N','P','F','C']);
for (const tile of classes) {
  const file = path.join(destination, `${tile}__hf_base.png`);
  try {
    const metadata = await sharp(file).metadata();
    if (metadata.format !== 'png' || !metadata.width || !metadata.height) throw new Error('invalid PNG');
    await sharp(file, {failOn:'error'}).raw().toBuffer();
  } catch (error) {
    throw new Error(`Bootstrap base missing or invalid for ${tile}: ${file}`, {cause:error});
  }
}
const templates = { '4p': '4p__6c_friend.png', '3s': '3s__e48_friend.png', '8s': '8s__fourplayer_friend.png' };
const selection = process.argv[3] ?? '4p';
if (!Object.hasOwn(templates, selection)) throw new Error('Template must be 4p, 3s or 8s');
const filename = templates[selection];
const source = path.join(root, 'templates/client', filename);
const target = path.join(destination, filename);
let alreadyPresent = false;
try {
  await copyFile(source, target, constants.COPYFILE_EXCL);
} catch (error) {
  if (error?.code !== 'EEXIST') throw error;
  const [existing, expected] = await Promise.all([readFile(target), readFile(source)]);
  if (!existing.equals(expected)) throw new Error(`Existing ${filename} differs; preserved without changes`);
  alreadyPresent = true;
}
console.log(JSON.stringify({ destination, installed: filename, alreadyPresent, bootstrapBaseFilesChecked: 34, templateIdentityVerified: false, accuracyVerified: false, requiresOperatorRestart: true }));
