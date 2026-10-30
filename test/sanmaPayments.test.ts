import { test } from "node:test";
import assert from "node:assert/strict";
import { calculateSanmaPayments, type SanmaPaymentInput } from "../src/game/sanmaPayments.js";

const pay = (input: Omit<SanmaPaymentInput, "tsumoLoss">) => calculateSanmaPayments({ ...input, tsumoLoss: true } as SanmaPaymentInput);

test("ron: dealer and nondealer, with independent 100-point rounding", () => {
  assert.deepEqual(pay({ basicPoints: 480, winner: "east", method: "ron", discarder: "west" } as SanmaPaymentInput), { east: 2900, south: 0, west: -2900 });
  assert.deepEqual(pay({ basicPoints: 480, winner: "south", method: "ron", discarder: "east" } as SanmaPaymentInput), { east: -2000, south: 2000, west: 0 });
});

test("tsumo loss: each present opponent pays the standard four-player share", () => {
  assert.deepEqual(pay({ basicPoints: 480, winner: "east", method: "tsumo" }), { east: 2000, south: -1000, west: -1000 });
  assert.deepEqual(pay({ basicPoints: 480, winner: "south", method: "tsumo" }), { east: -1000, south: 1500, west: -500 });
  // Four-player equivalent at 480 base: dealer tsumo 1000×3; child tsumo
  // dealer 1000 + two children 500×2. The missing child pays nothing here.
  assert.equal(3000 - 2000, 1000);
  assert.equal(2000 - 1500, 500);
  assert.deepEqual(pay({ basicPoints: 2000, winner: "west", method: "tsumo" }), { east: -4000, south: -2000, west: 6000 });
});

test("reject unsupported adjustments, invalid seats and inexact inputs", () => {
  const base = { basicPoints: 480, winner: "east", method: "tsumo", tsumoLoss: true };
  for (const extra of [{ honba: 1 }, { riichiSticks: 1 }, { pao: true }, { tsumoLoss: false },
    { discarder: "south" }, { winner: "north" }, { basicPoints: 0 }, { basicPoints: 0.5 },
    { basicPoints: Number.MAX_SAFE_INTEGER }, { method: "ron", discarder: "east" }]) {
    assert.throws(() => calculateSanmaPayments({ ...base, ...extra } as SanmaPaymentInput));
  }
});
