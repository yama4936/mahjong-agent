import assert from "node:assert/strict";
import test from "node:test";
import sharp from "sharp";
import { existsSync } from "node:fs";
import { HybridTileRecognizer, mapHybridLabel } from "../src/recognition/hybridTileRecognizer.js";

test("uncertain red override cannot replace nine-man while real red fives survive", {
  skip: !existsSync(".runtime/hybrid-vision/cvmaj-pretrained.tar") || !existsSync(".runtime/hybrid-vision/automajsoul-best-model.pt"),
}, async () => {
  const frame = "artifacts/live/green-dragon-pon-missed-after-called-river-removal-20260928.png";
  const crops = [{ left: 1665, top: 947, width: 85, height: 76 },
    { left: 410, top: 923, width: 95, height: 149 },
    { left: 600, top: 923, width: 95, height: 149 }];
  const recognizer = new HybridTileRecognizer();
  try {
    const predictions = await recognizer.classifyTileImages(await Promise.all(
      crops.map(crop => sharp(frame).extract(crop).png().toBuffer())));
    assert.deepEqual(predictions.map(item => item.tile), ["9m", "0p", "0s"]);
    assert.equal(predictions[0]?.selectedBy, "normal");
    assert.ok((predictions[0]?.redPrediction.confidence ?? 1) < 0.5);
    assert.ok(predictions.slice(1).every(item => item.selectedBy === "red-gate"));
  } finally { await recognizer.close(); }
});

test("maps cvmaj honors and AutoMajsoul red fives", () => {
  assert.equal(mapHybridLabel("1z"), "E");
  assert.equal(mapHybridLabel("7z"), "C");
  assert.equal(mapHybridLabel("0m"), "0m");
  assert.equal(mapHybridLabel("5s"), "5s");
});

test("hybrid classifier preserves normal and red-gate decisions", async () => {
  const recognizer = new HybridTileRecognizer() as any;
  recognizer.predict = async () => [
    {
      label: "3p", confidence: 0.98, runnerUpLabel: "4p", runnerUpConfidence: 0.01,
      selectedBy: "normal", normalPrediction: { label: "3p", confidence: 0.98 }, redPrediction: { label: "3p", confidence: 0.91 },
    },
    {
      label: "0m", confidence: 0.97, runnerUpLabel: "5m", runnerUpConfidence: 0.02,
      selectedBy: "red-gate", normalPrediction: { label: "5m", confidence: 0.99 }, redPrediction: { label: "5m-", confidence: 0.97 },
    },
  ];
  const result = await recognizer.classifyTileImages([Buffer.from("normal"), Buffer.from("red")]);
  assert.deepEqual(result.map((prediction: any) => prediction.tile), ["3p", "0m"]);
  assert.deepEqual(result.map((prediction: any) => prediction.selectedBy), ["normal", "red-gate"]);
  assert.equal(result[1]?.normalPrediction.tile, "5m");
  assert.equal(result[1]?.redPrediction.label, "5m-");
});
