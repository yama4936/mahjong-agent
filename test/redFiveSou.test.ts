import assert from "node:assert/strict";
import test from "node:test";
import sharp from "sharp";
import { correctRedFiveSou, redFiveSouEvidence } from "../src/recognition/redFiveSou.js";
import { parseGameState } from "../src/game/state.js";
import { deterministicAdvice } from "../src/evaluation/advisor.js";

async function evidence(image: string, left: number, top: number, width: number, height: number) {
  const rgb = await sharp(image).extract({ left, top, width, height })
    .resize(44, 64, { fit: "fill" }).removeAlpha().toColourspace("srgb").raw().toBuffer();
  return redFiveSouEvidence(rgb);
}

test("central bamboo distinguishes visually labelled ordinary and red five sou renderings", async () => {
  // Labels are from the visible glyphs, not bootstrap filenames or model output.
  const prompt = "artifacts/live/green-dragon-pon-missed-after-called-river-removal-20260928.png";
  assert.equal((await evidence(prompt, 600, 923, 95, 149)).supportsRed, true);
  assert.equal((await evidence(prompt, 695, 923, 95, 149)).supportsRed, false);
  const live = await evidence("artifacts/live/red-five-sou-read-normal-in-fixed-regression-20260928.jpg",
    1266, 926, 93, 146);
  assert.deepEqual(live, { red: 161, green: 0, supportsRed: true });
  const fullRed = await evidence("artifacts/live/left-melds-chi-pon-20260928.jpg", 982, 926, 92, 146);
  assert.equal(fullRed.supportsRed, true);
});

test("blank evidence and malformed pixel buffers cannot support red five sou", () => {
  assert.equal(redFiveSouEvidence(new Uint8Array(44 * 64 * 3).fill(240)).supportsRed, false);
  assert.throws(() => redFiveSouEvidence(new Uint8Array(44 * 64 * 4)), /44x64 RGB/);
});

test("sou color correction is suit-gated and ignores red at the outer bamboo", () => {
  const rgb = new Uint8Array(44 * 64 * 3).fill(240);
  const paint = (left: number, top: number, width: number, height: number, color: number[]) => {
    for (let y = top; y < top + height; y++) for (let x = left; x < left + width; x++) {
      rgb.set(color, (y * 44 + x) * 3);
    }
  };
  paint(5, 7, 8, 20, [190, 35, 35]); // Ordinary five sou can have a red outer glyph.
  paint(18, 20, 6, 25, [30, 155, 45]);
  assert.equal(correctRedFiveSou("5s", rgb), "5s");
  paint(18, 20, 6, 25, [190, 35, 35]);
  assert.equal(correctRedFiveSou("5s", rgb), "0s");
  for (const tile of ["5p", "5m", "4m", "3s", "0s", "0p", "0m"] as const) {
    assert.equal(correctRedFiveSou(tile, rgb), tile);
  }
});

test("live first-turn red identity changes local discard from red five sou to west", () => {
  const input = {
    round: "east_1", honba: 0, riichiSticks: 0, seat: "north",
    scores: { north: 25000, east: 25000, south: 25000, west: 25000 },
    hand: ["4m", "5m", "8m", "8m", "9m", "1p", "2p", "5p", "6p", "6p", "3s", "5s", "W"],
    draw: "2s", doraIndicators: ["8s"], ownDiscards: [], melds: [], visibleTiles: [],
    openMelds: 0, turn: 0, remainingTiles: 66, phase: "self_turn",
    recognitionConfidence: 0.8549699532658859, publicStateConfidence: 0,
    riichiDeclared: false, availableUiActions: [],
    opponents: [
      { seat: "east", discards: ["P"], riichi: false, openMelds: 0, openMeldsObserved: false, melds: [] },
      { seat: "south", discards: ["7p"], riichi: false, openMelds: 0, openMeldsObserved: false, melds: [] },
      { seat: "west", discards: ["N"], riichi: false, openMelds: 0, openMeldsObserved: false, melds: [] },
    ],
  };
  const old = deterministicAdvice(parseGameState(input));
  const corrected = deterministicAdvice(parseGameState({ ...input,
    hand: input.hand.map((tile, index) => index === 11 ? "0s" : tile) }));
  assert.equal(old.tile, "5s");
  assert.equal(corrected.tile, "W");
  assert.equal(old.candidates.find(c => c.tile === "W")!.estimatedValue, 2000);
  assert.equal(corrected.candidates.find(c => c.tile === "W")!.estimatedValue, 3900);
  // This proves policy sensitivity, not a counterfactual match win.
});
