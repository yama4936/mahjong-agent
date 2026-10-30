import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { calculateSanmaPayments } from "../src/game/sanmaPayments.js";

const python = process.env.SANMA_SCORING_PYTHON;
const hand = ["9m", "9m", "0p", "5p", "5p", "6p", "7p", "8p", "2s", "3s", "4s", "S", "S", "S"];
const input = { hand, winner: "3s", seat: "west", roundWind: "east", riichi: true, indicators: ["W"], uraIndicators: ["N"], kita: 1, honba: 0, deposits: 0, pao: false, melds: [], tsumoLoss: true, situationalYakuExcluded: true };
test("experimental closed scorer and payments reproduce recorded tsumo without deposits", { skip: !python }, () => {
  const result = spawnSync(python!, ["python/sanma_closed_experiment.py"], { input: JSON.stringify(input), encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  const score = JSON.parse(result.stdout);
  assert.deepEqual([score.han, score.fu, score.basicPoints], [5, 40, 2000]);
  assert.deepEqual(calculateSanmaPayments({ method: "tsumo", winner: "west", basicPoints: score.basicPoints, tsumoLoss: true }), { east: -4000, south: -2000, west: 6000 });
  assert.deepEqual(calculateSanmaPayments({ method: "tsumo", winner: "east", basicPoints: score.basicPoints, tsumoLoss: true }), { east: 8000, south: -4000, west: -4000 });
});
