import assert from "node:assert/strict";
import test from "node:test";
import { VitTileRecognizer } from "../src/recognition/vitRecognizer.js";

test("ViT public-tile classification chunks batches larger than fourteen", async () => {
  const recognizer = new VitTileRecognizer() as any;
  const batchSizes: number[] = [];
  recognizer.predict = async (images: Buffer[]) => {
    batchSizes.push(images.length);
    return images.map(() => ({
      label: "1n",
      confidence: 0.99,
      runnerUpLabel: "2n",
      runnerUpConfidence: 0.01,
    }));
  };
  const predictions = await recognizer.classifyTileImages(Array.from({ length: 31 }, () => Buffer.from("tile")));
  assert.deepEqual(batchSizes, [14, 14, 3]);
  assert.equal(predictions.length, 31);
  assert.ok(predictions.every((prediction: any) => prediction.tile === "1m"));
});

test("ViT public-tile classification accepts an empty candidate batch", async () => {
  const recognizer = new VitTileRecognizer() as any;
  assert.deepEqual(await recognizer.classifyTileImages([]), []);
});
