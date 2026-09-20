import { readFile } from "node:fs/promises";
import { createInterface } from "node:readline";
import { HybridTileRecognizer } from "./hybridTileRecognizer.js";
import { layoutSchema } from "./layout.js";
import { recognizeConfiguredPublicTilesWithVit, toPublicTileObservation } from "./publicTileRecognizer.js";

const [layoutPath, ownSeatArgument = "east"] = process.argv.slice(2);
if (!layoutPath) throw new Error("Usage: publicRecognitionServer <layout.json> [seat]");
if (!(["east", "south", "west", "north"] as const).includes(ownSeatArgument as any)) {
  throw new Error(`Invalid seat: ${ownSeatArgument}`);
}
const ownSeat = ownSeatArgument as "east" | "south" | "west" | "north";
const loadedLayout = layoutSchema.parse(JSON.parse(await readFile(layoutPath, "utf8")));
let layout = loadedLayout;
if (!loadedLayout.publicTileRegions?.doraIndicators) {
  try {
    const fallback = layoutSchema.parse(JSON.parse(await readFile("config/layout.example.json", "utf8")));
    if (fallback.viewport.width === loadedLayout.viewport.width && fallback.viewport.height === loadedLayout.viewport.height
      && fallback.publicTileRegions?.doraIndicators) {
      layout = {
        ...loadedLayout,
        publicTileRegions: {
          ...loadedLayout.publicTileRegions,
          doraIndicators: fallback.publicTileRegions.doraIndicators,
        },
      };
    }
  } catch {}
}
const recognizer = new HybridTileRecognizer();
process.stdout.write(`${JSON.stringify({ ready: true, backend: "hybrid" })}\n`);

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of lines) {
  if (!line.trim()) continue;
  let id: unknown;
  try {
    const request = JSON.parse(line) as { id: unknown; screenshot: string; capturedAt?: string };
    id = request.id;
    const startedAt = performance.now();
    const recognition = await recognizeConfiguredPublicTilesWithVit(
      request.screenshot,
      layout,
      recognizer,
    );
    const recognitionLatencyMs = Math.max(0, Math.round(performance.now() - startedAt));
    const observation = {
      ...toPublicTileObservation(recognition, ownSeat),
      capturedAt: request.capturedAt ?? new Date().toISOString(),
      recognizedAt: new Date().toISOString(),
      recognitionLatencyMs,
      configuredRegions: Object.keys(layout.publicTileRegions ?? {}),
    };
    process.stdout.write(`${JSON.stringify({ id, result: observation })}\n`);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({ id, error: error instanceof Error ? error.message : String(error) })}\n`);
  }
}
await recognizer.close();
