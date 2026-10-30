import { test } from "node:test";
import assert from "node:assert/strict";
import { countSanmaKitaDora } from "../src/game/sanmaKitaDora.js";

test("count only extracted north dora, including every west indicator", () => {
  assert.equal(countSanmaKitaDora({ extractedNorthCount: 0, westIndicatorCount: 2 }), 0);
  assert.equal(countSanmaKitaDora({ extractedNorthCount: 3, westIndicatorCount: 0 }), 3);
  assert.equal(countSanmaKitaDora({ extractedNorthCount: 2, westIndicatorCount: 1 }), 4);
  assert.equal(countSanmaKitaDora({ extractedNorthCount: 2, westIndicatorCount: 2 }), 6);
  assert.equal(countSanmaKitaDora({ extractedNorthCount: 4, westIndicatorCount: 4 }), 20);
});

test("reject invalid, missing and unsupported inputs", () => {
  const good = { extractedNorthCount: 1, westIndicatorCount: 1 };
  for (const count of [-1, 5, 1.2, NaN, Infinity]) {
    assert.throws(() => countSanmaKitaDora({ ...good, extractedNorthCount: count }));
    assert.throws(() => countSanmaKitaDora({ ...good, westIndicatorCount: count }));
  }
  assert.throws(() => countSanmaKitaDora({ ...good, handNorthCount: 1 } as typeof good));
  assert.throws(() => countSanmaKitaDora({ extractedNorthCount: 1 } as typeof good));
});
