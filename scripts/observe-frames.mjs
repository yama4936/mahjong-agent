#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { mkdir, writeFile, appendFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export function parseOptions(args) {
  const values = {};
  for (let i = 0; i < args.length; i++) {
    const name = args[i];
    if (!['--interval-ms', '--count', '--output', '--cdp'].includes(name) || values[name] !== undefined || !args[i + 1] || args[i + 1].startsWith('--')) throw new Error(`Invalid option: ${name}`);
    values[name] = args[++i];
  }
  for (const name of ['--interval-ms', '--count']) {
    if (!/^[1-9]\d*$/.test(values[name] ?? '') || !Number.isSafeInteger(Number(values[name]))) throw new Error(`${name} must be an explicit positive integer`);
  }
  if (!values['--output']) throw new Error('--output is required');
  return { intervalMs: Number(values['--interval-ms']), count: Number(values['--count']), output: values['--output'], cdp: values['--cdp'] ?? 'http://127.0.0.1:9222' };
}

export function selectGamePage(contexts) {
  const pages = contexts.flatMap(context => context.pages()).filter(page => {
    try { const url = new URL(page.url()); return url.protocol === 'https:' && url.hostname === 'game.mahjongsoul.com'; } catch { return false; }
  });
  if (pages.length !== 1) throw new Error(`Expected exactly one Mahjong Soul page, found ${pages.length}`);
  return pages[0];
}

export async function captureFrames(page, options, dependencies = {}) {
  const sleep = dependencies.sleep ?? (ms => new Promise(resolve => setTimeout(resolve, ms)));
  const now = dependencies.now ?? (() => new Date());
  await mkdir(options.output, { recursive: true });
  const manifest = path.join(options.output, 'manifest.jsonl');
  for (let i = 0; i < options.count; i++) {
    // Capture only; never navigate, click, resize, or close the existing browser.
    const startedAt = now().toISOString();
    const png = await page.screenshot({ type: 'png', timeout: 15000 });
    const capturedAt = now().toISOString();
    const filename = `frame-${String(i + 1).padStart(6, '0')}-${capturedAt.replace(/[:.]/g, '-')}.png`;
    await writeFile(path.join(options.output, filename), png, { flag: 'wx', mode: 0o600 });
    await appendFile(manifest, JSON.stringify({ startedAt, capturedAt, filename, sha256: createHash('sha256').update(png).digest('hex') }) + '\n', { mode: 0o600 });
    if (i + 1 < options.count) await sleep(options.intervalMs);
  }
}

async function main() {
  const options = parseOptions(process.argv.slice(2));
  const { chromium } = await import('playwright');
  const browser = await chromium.connectOverCDP(options.cdp);
  const page = selectGamePage(browser.contexts());
  await captureFrames(page, options);
  // Exit drops only this CDP connection; browser.close() would close the shared browser.
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().then(() => process.exit(0), error => { console.error(error.message); process.exit(1); });
}
