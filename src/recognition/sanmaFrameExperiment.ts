import { createHash } from "node:crypto";
import sharp from "sharp";
import { evaluateDiscards } from "../game/ukeire.js";
import { proposeLiveHandLayout } from "./handLayoutProposal.js";
import type { ScreenLayout } from "./layout.js";
import { recognizeHand } from "./templateMatcher.js";
import { classifySanmaButtonCrop, type ExperimentalTemplates } from "./sanmaButtonExperiment.js";
import { recognizeSanmaPublicCandidates, type PublicVitClassifier } from "./publicTileRecognizer.js";

/** Read-only frame experiment. No result in this function authorizes play. */
export async function inspectSanmaFrame(input: {
  frame: Buffer; layout: ScreenLayout; templates: string; buttonTemplates: ExperimentalTemplates;
  ownSeat: "east" | "south" | "west"; publicClassifier: PublicVitClassifier;
}) {
  if (!Buffer.isBuffer(input.frame)) throw new Error("Frame bytes required");
  // The same immutable snapshot is used for every branch. Paths are not
  // accepted, since a live screenshot file can change during recognition.
  const frame = Buffer.from(input.frame);
  const digest = createHash("sha256").update(frame).digest("hex");
  const image = sharp(frame);
  const dimensions = await image.metadata();
  if (dimensions.width !== 1920 || dimensions.height !== 1080) throw new Error("Unreviewed frame dimensions");
  const handPromise = (async () => {
    const proposal = await proposeLiveHandLayout(frame);
    return recognizeHand(frame, { ...input.layout, ...proposal }, input.templates);
  })();
  const publicPromise = recognizeSanmaPublicCandidates(frame, input.layout, input.ownSeat, input.publicClassifier);
  const buttonPromise = (async () => {
    const crop = await sharp(frame).extract({ left: 890, top: 785, width: 245, height: 90 }).png().toBuffer();
    return classifySanmaButtonCrop(crop, input.buttonTemplates);
  })();
  const [hand, publicTiles, button] = await Promise.allSettled([handPromise, publicPromise, buttonPromise]);
  const describe = <T>(value: PromiseSettledResult<T>) => value.status === "fulfilled"
    ? { status: "candidate" as const, value: value.value }
    : { status: "unresolved" as const, reason: value.reason instanceof Error ? value.reason.message : String(value.reason) };
  // A single cropped button, missing public tiles and uncertain meld/riichi
  // status cannot authorize a decision. Produce only hypothetical closed-hand
  // shape calculations, assuming zero outside tiles; they are not a policy.
  let shape: { status: "hypothesis"; assumptions: string[]; rows: ReturnType<typeof evaluateDiscards> } | { status: "unresolved"; reason: string };
  if (hand.status === "fulfilled" && hand.value.safe && hand.value.tiles.length === 14) {
    try {
      shape = { status: "hypothesis", assumptions: ["closed hand", "no visible tiles", "no action priority", "hand labels correct"],
        rows: evaluateDiscards(hand.value.tiles, [], 0, "sanma") };
    } catch (error) { shape = { status: "unresolved", reason: error instanceof Error ? error.message : String(error) }; }
  } else shape = { status: "unresolved", reason: "No complete candidate hand" };
  return { scope: "offline_untrusted_sanma_frame" as const, digest, hand: describe(hand),
    publicTiles: describe(publicTiles), button: describe(button), shape,
    decision: { status: "blocked" as const, reasons: ["hand recognition unverified", "public observations incomplete",
      "single crop does not establish all available actions", "turn, meld and riichi status unverified"] },
    operationAuthorized: false as const };
}
