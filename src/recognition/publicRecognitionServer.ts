import { readFile } from "node:fs/promises";
import { createInterface } from "node:readline";
import { HybridTileRecognizer } from "./hybridTileRecognizer.js";
import { layoutSchema } from "./layout.js";
import { recognizeConfiguredPublicTilesWithVit, toPublicTileObservation } from "./publicTileRecognizer.js";
import { JevClient, type JevHandPlan } from "../jev/client.js";

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
const jev = process.env.TYPESAFE_API_KEY ? new JevClient(process.env.TYPESAFE_API_KEY) : undefined;
const planDeadlineMs = Number(process.env.JEV_HAND_PLAN_DEADLINE_MS ?? 2_500);
if (!Number.isFinite(planDeadlineMs) || planDeadlineMs <= 0) throw new Error("Invalid Jev hand-plan deadline");
let cachedPlanKey: string | undefined;
let cachedPlan: JevHandPlan | undefined;

async function choosePlan(request: { concealedTiles?: string[]; openMelds?: number; seat?: string; round?: string }): Promise<JevHandPlan | undefined> {
  if (!jev || !request.concealedTiles || request.openMelds === undefined) return undefined;
  const key = `${request.openMelds}:${[...request.concealedTiles].sort().join(",")}`;
  if (key === cachedPlanKey && cachedPlan) return cachedPlan;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), planDeadlineMs);
  try {
    const plan = await jev.chooseHandPlan({
      hand: request.concealedTiles, openMelds: request.openMelds,
      ...(request.seat ? { seat: request.seat } : {}), ...(request.round ? { round: request.round } : {}),
    }, controller.signal);
    cachedPlanKey = key;
    cachedPlan = plan;
    return plan;
  } catch {
    return undefined;
  } finally {
    clearTimeout(timeout);
  }
}
process.stdout.write(`${JSON.stringify({ ready: true, backend: "hybrid" })}\n`);

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of lines) {
  if (!line.trim()) continue;
  let id: unknown;
  try {
    const request = JSON.parse(line) as {
      id: unknown; screenshot: string; capturedAt?: string;
      concealedTiles?: string[]; openMelds?: number; seat?: string; round?: string;
    };
    id = request.id;
    const startedAt = performance.now();
    const recognitionPromise = recognizeConfiguredPublicTilesWithVit(
      request.screenshot,
      layout,
      recognizer,
    );
    const planPromise = choosePlan(request);
    const recognition = await recognitionPromise;
    const recognitionLatencyMs = Math.max(0, Math.round(performance.now() - startedAt));
    const handPlan = await planPromise;
    const observation = {
      ...toPublicTileObservation(recognition, ownSeat),
      capturedAt: request.capturedAt ?? new Date().toISOString(),
      recognizedAt: new Date().toISOString(),
      recognitionLatencyMs,
      configuredRegions: Object.keys(layout.publicTileRegions ?? {}),
      ...(handPlan ? { handPlan } : {}),
    };
    process.stdout.write(`${JSON.stringify({ id, result: observation })}\n`);
  } catch (error) {
    process.stdout.write(`${JSON.stringify({ id, error: error instanceof Error ? error.message : String(error) })}\n`);
  }
}
await recognizer.close();
