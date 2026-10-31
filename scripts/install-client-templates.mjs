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
const source = path.join(root, 'templates/client/4p__6c_friend.png');
const target = path.join(destination, '4p__6c_friend.png');
let alreadyPresent = false;
try {
  await copyFile(source, target, constants.COPYFILE_EXCL);
} catch (error) {
  if (error?.code !== 'EEXIST') throw error;
  const [existing, expected] = await Promise.all([readFile(target), readFile(source)]);
  if (!existing.equals(expected)) throw new Error('Existing 4p__6c_friend.png differs; preserved without changes');
  alreadyPresent = true;
}
console.log(JSON.stringify({ destination, installed: '4p__6c_friend.png', alreadyPresent, bootstrapBaseFilesChecked: 34, templateIdentityVerified: false, accuracyVerified: false, requiresOperatorRestart: true }));
