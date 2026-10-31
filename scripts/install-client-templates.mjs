// Explicit installation, performed between matches. Existing matches must not
// have their templates changed while the recognition process is running.
import { constants } from 'node:fs';
import { access, copyFile, readFile } from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const destination = process.argv[2] ? path.resolve(process.argv[2]) : path.join(root, 'templates/bootstrap');
// Refuse to create an incomplete stand-alone template set.
await access(path.join(destination, '1m__hf_base.png'));
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
console.log(JSON.stringify({ destination, installed: '4p__6c_friend.png', alreadyPresent, requiresOperatorRestart: true }));
