// Explicit installation, performed between matches. Existing matches must not
// have their templates changed while the recognition process is running.
import { access, copyFile } from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const destination = process.argv[2] ? path.resolve(process.argv[2]) : path.join(root, 'templates/bootstrap');
// Refuse to create an incomplete stand-alone template set.
await access(path.join(destination, '1m__hf_base.png'));
await copyFile(path.join(root, 'templates/client/4p__6c_friend.png'), path.join(destination, '4p__6c_friend.png'));
console.log(JSON.stringify({ destination, installed: '4p__6c_friend.png', requiresOperatorRestart: true }));
