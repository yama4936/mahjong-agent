import { access, mkdir } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright";

const profile = path.resolve(process.env.JANTAMA_BROWSER_PROFILE ?? ".runtime/browser-profile");
const port = Number(process.env.JANTAMA_CDP_PORT ?? 9222);
const headless = /^(?:1|true|yes)$/i.test(process.env.JANTAMA_HEADLESS ?? "false");
const softwareRendering = /^(?:1|true|yes)$/i.test(process.env.JANTAMA_SOFTWARE_RENDERING ?? "false");
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error("JANTAMA_CDP_PORT must be an integer from 1024 to 65535");
await mkdir(profile, { recursive: true, mode: 0o700 });

async function installedChrome() {
  if (process.env.JANTAMA_CHROME_BIN) return process.env.JANTAMA_CHROME_BIN;
  if (process.platform !== "win32") return undefined;
  const candidates = [
    process.env.ProgramFiles && path.join(process.env.ProgramFiles, "Google/Chrome/Application/chrome.exe"),
    process.env["ProgramFiles(x86)"] && path.join(process.env["ProgramFiles(x86)"], "Google/Chrome/Application/chrome.exe"),
    process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, "Google/Chrome/Application/chrome.exe"),
  ].filter(Boolean);
  for (const candidate of candidates) {
    try {
      await access(candidate);
      return candidate;
    } catch {}
  }
  return undefined;
}

const executablePath = await installedChrome();

const context = await chromium.launchPersistentContext(profile, {
  headless,
  viewport: { width: 1920, height: 1080 },
  ...(executablePath ? { executablePath } : {}),
  args: [
    `--remote-debugging-port=${port}`,
    "--remote-debugging-address=127.0.0.1",
    "--disable-backgrounding-occluded-windows",
    ...(softwareRendering ? ["--enable-unsafe-swiftshader", "--use-angle=swiftshader-webgl"] : []),
  ],
});

const pages = context.pages();
const page = pages.find((candidate) => candidate.url().includes("mahjongsoul.com")) ?? pages[0] ?? await context.newPage();
if (!page.url().includes("mahjongsoul.com")) await page.goto("https://game.mahjongsoul.com/index.html");
console.log(JSON.stringify({ cdp: `http://127.0.0.1:${port}`, profile, executablePath: executablePath ?? "playwright-chromium", rendering: softwareRendering ? "software" : "gpu", page: page.url() }));

let closing = false;
async function close() {
  if (closing) return;
  closing = true;
  await context.close().catch(() => {});
  process.exit(0);
}
process.once("SIGINT", close);
process.once("SIGTERM", close);
await new Promise((resolve) => context.on("close", resolve));
