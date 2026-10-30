import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { classifySanmaButtonCrop, EXPERIMENTAL_BUTTONS, type ExperimentalTemplates } from "../src/recognition/sanmaButtonExperiment.js";

const directory = "test/fixtures/sanma-buttons";
const frame = (name: string) => readFile(path.join(directory, `${name}.png`));
async function templates(): Promise<ExperimentalTemplates> {
  return Object.fromEntries(await Promise.all(EXPERIMENTAL_BUTTONS.map(async name => [name, await frame(name)]))) as ExperimentalTemplates;
}

test("two real kita crops and competing real action crops remain distinct", async () => {
  const refs = await templates();
  const unseen = await classifySanmaButtonCrop(await frame("kita2"), refs);
  assert.equal(unseen.status, "matched");
  if (unseen.status === "matched") assert.equal(unseen.action, "kita");
  for (const action of EXPERIMENTAL_BUTTONS) {
    const result = await classifySanmaButtonCrop(await frame(action), refs);
    assert.equal(result.status, "matched");
    if (result.status === "matched") assert.equal(result.action, action);
  }
});

test("empty crop and competing equal templates cannot authorize a match", async () => {
  const refs = await templates();
  assert.equal((await classifySanmaButtonCrop(await frame("empty"), refs)).status, "unresolved");
  const tied = await classifySanmaButtonCrop(await frame("kita2"), { ...refs, tsumo: refs.kita });
  assert.equal(tied.status, "unresolved");
  if (tied.status === "unresolved") assert.equal(tied.reason, "ambiguous");
  await assert.rejects(classifySanmaButtonCrop(await frame("kita"), { ...refs, pon: undefined } as unknown as ExperimentalTemplates));
});
