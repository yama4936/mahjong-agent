import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import sharp from "sharp";
import { EXPERIMENTAL_BUTTONS, type ExperimentalTemplates } from "../src/recognition/sanmaButtonExperiment.js";
import { inspectSanmaButtonRow } from "../src/recognition/sanmaButtonRowExperiment.js";
const row = (name: string) => readFile(`test/fixtures/sanma-button-rows/${name}.png`);
async function setup() {
  const templates = Object.fromEntries(await Promise.all(EXPERIMENTAL_BUTTONS.map(async name => [name, await readFile(`test/fixtures/sanma-buttons/${name}.png`)]))) as ExperimentalTemplates;
  const skip = await sharp(await row("kita")).extract({ left: 580, top: 0, width: 245, height: 90 }).png().toBuffer();
  return { templates, skip, empty: await row("empty") };
}
test("observed action rows include shifted pon and kan, while every result stays untrusted", async () => {
  const { templates, skip, empty } = await setup();
  for (const [name, expected] of [["kita2", ["kita", "skip"]], ["riichi", ["riichi", "skip"]], ["pon-kan", ["pon", "kan", "skip"]], ["tsumo", ["tsumo", "skip"]]] as const) {
    const result = await inspectSanmaButtonRow(await row(name), templates, skip, empty);
    assert.deepEqual(result.slots.flatMap(s => s.status === "candidate" ? [s.action] : []), expected);
    assert.equal(result.complete, false);
    assert.equal(result.operationAuthorized, false);
  }
});
test("empty scene is only a candidate, while obscured and invalid rows fail closed", async () => {
  const { templates, skip, empty } = await setup();
  const blank = await inspectSanmaButtonRow(empty, templates, skip, empty);
  assert.ok(blank.slots.every(s => s.status === "empty_candidate"));
  const obscured = await inspectSanmaButtonRow(await row("empty2"), templates, skip, empty);
  assert.equal(obscured.slots[2]?.status, "unresolved");
  await assert.rejects(inspectSanmaButtonRow(await readFile("test/fixtures/sanma-buttons/kita.png"), templates, skip, empty));
});
test("unknown visual obstruction is never inferred as an empty slot", async () => {
  const { templates, skip, empty } = await setup();
  const black = await sharp({ create: { width: 245, height: 90, channels: 3, background: "black" } }).png().toBuffer();
  const rowWithUnknown = await sharp(empty).composite([{ input: black, left: 290, top: 0 }]).png().toBuffer();
  const result = await inspectSanmaButtonRow(rowWithUnknown, templates, skip, empty);
  assert.equal(result.slots[1]?.status, "unresolved");
});


test("overlapped skip stays a diagnostic candidate and requires the clear portion and competing labels", async () => {
  const { templates, skip, empty } = await setup();
  for (const name of ["riichi", "tsumo"]) {
    const result = await inspectSanmaButtonRow(await row(name), templates, skip, empty);
    const slot = result.slots[2]!;
    assert.equal(slot.status, "candidate");
    if (slot.status === "candidate") {
      assert.equal(slot.action, "skip");
      assert.equal(slot.evidence, "partially_occluded_skip");
      assert.ok(slot.confidence >= 0.995);
    }
    assert.equal(result.complete, false);
    assert.equal(result.operationAuthorized, false);
  }
  const ambiguous = await inspectSanmaButtonRow(await row("riichi"), { ...templates, pon: skip }, skip, empty);
  assert.equal(ambiguous.slots[2]?.status, "unresolved");
  const black = await sharp({ create: { width: 45, height: 90, channels: 3, background: "black" } }).png().toBuffer();
  const corrupted = await sharp(await row("riichi")).composite([{ input: black, left: 780, top: 0 }]).png().toBuffer();
  const result = await inspectSanmaButtonRow(corrupted, templates, skip, empty);
  assert.equal(result.slots[2]?.status, "unresolved");
});
