import assert from "node:assert/strict";
import test from "node:test";
import { HybridTileRecognizer, mapHybridLabel } from "../src/recognition/hybridTileRecognizer.js";

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
