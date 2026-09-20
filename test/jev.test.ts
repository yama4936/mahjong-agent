import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "node:http";
import { once } from "node:events";
import { buildJevReactionRequest, buildJevRequest, JevClient } from "../src/jev/client.js";
import { deterministicAdvice } from "../src/evaluation/advisor.js";
import { parseGameState } from "../src/game/state.js";

const state = parseGameState({
  hand: ["1m", "2m", "3m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s", "E"],
  draw: "6p",
});

test("Jev adapter sends bounded choices and validates a response", async () => {
  const candidates = deterministicAdvice(state).candidates;
  let observedAuthorization = "";
  let observedState: any;
  const server = createServer((request, response) => {
    observedAuthorization = request.headers.authorization ?? "";
    let body = "";
    request.on("data", (chunk) => { body += chunk; });
    request.on("end", () => {
      const parsed = JSON.parse(body);
      observedState = parsed.state;
      const ids = Object.keys(parsed.questions.action.criteria);
      const probabilities = Object.fromEntries(ids.map((id: string, index: number) => [id, index === 0 ? 1 : 0]));
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({
        model: "jev-test",
        answers: { action: { type: "choice", choice: ids[0], confidence: 1, probabilities } },
        usage: { input_tokens: 100, output_tokens: 10 },
      }));
    });
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  try {
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("Test server failed");
    const result = await new JevClient("test-key", `http://127.0.0.1:${address.port}`, "jev-test").chooseDiscard(state, candidates);
    assert.equal(result.actionId, candidates[0]!.actionId);
    assert.equal(result.confidence, 1);
    assert.equal(observedAuthorization, "Bearer test-key");
    assert.equal(result.promptVersion, "mahjong-discard-v2");
    assert.equal(result.usage?.input_tokens, 100);
    assert.equal(observedState.honba, 0);
    assert.deepEqual(observedState.ownDiscards, []);
    assert.deepEqual(observedState.opponents, []);
    assert.equal(observedState.promptVersion, "mahjong-discard-v2");
    assert.equal(observedState.candidates, undefined);
  } finally {
    server.close();
  }
});

test("balanced Jev prompt uses structured criteria without duplicate candidates", () => {
  const candidates = deterministicAdvice(state).candidates;
  const request = buildJevRequest(state, candidates, "jev-test", "balanced-v2");
  assert.equal(request.state.candidates, undefined);
  assert.equal(request.state.promptVersion, "mahjong-discard-v2");
  assert.equal(typeof request.questions.action.instructions, "object");
  assert.equal(typeof request.questions.action.criteria[candidates[0]!.actionId], "object");
});

test("legacy Jev prompt remains available for A/B evaluation", () => {
  const candidates = deterministicAdvice(state).candidates;
  const request = buildJevRequest(state, candidates, "jev-test", "legacy-v1");
  assert.ok(Array.isArray(request.state.candidates));
  assert.equal(request.state.promptVersion, "mahjong-discard-v1");
  assert.equal(typeof request.questions.action.instructions, "string");
});

test("Jev adapter rejects malformed usage metadata", async () => {
  const candidates = deterministicAdvice(state).candidates;
  const server = createServer((request, response) => {
    let body = "";
    request.on("data", (chunk) => { body += chunk; });
    request.on("end", () => {
      const ids = Object.keys(JSON.parse(body).questions.action.criteria);
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({
        model: "jev-test",
        answers: {
          action: {
            type: "choice",
            choice: ids[0],
            confidence: 1,
            probabilities: Object.fromEntries(ids.map((id: string, index: number) => [id, index === 0 ? 1 : 0])),
          },
        },
        usage: { input_tokens: -1, output_tokens: 0 },
      }));
    });
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  try {
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("Test server failed");
    await assert.rejects(
      new JevClient("test-key", `http://127.0.0.1:${address.port}`, "jev-test").chooseDiscard(state, candidates),
      /Invalid Jev usage/,
    );
  } finally {
    server.close();
  }
});

test("Jev adapter rejects probability keys that do not match legal actions", async () => {
  const candidates = deterministicAdvice(state).candidates;
  const server = createServer((_request, response) => {
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify({
      model: "jev-test",
      answers: { action: { type: "choice", choice: candidates[0]!.actionId, confidence: 1, probabilities: { [candidates[0]!.actionId]: 1 } } },
    }));
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  try {
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("Test server failed");
    await assert.rejects(
      new JevClient("test-key", `http://127.0.0.1:${address.port}`, "jev-test").chooseDiscard(state, candidates),
      /probability keys/,
    );
  } finally {
    server.close();
  }
});

test("reaction request sends the hand, board, pending discard and only legal choices", () => {
  const reaction = parseGameState({
    hand: ["1m", "2m", "3m", "4m", "4m", "5m", "6m", "3p", "4p", "5p", "7s", "8s", "9s"],
    phase: "reaction", seat: "south", pendingDiscard: { tile: "4m", fromSeat: "east" },
    doraIndicators: ["3s"], ownDiscards: ["P"],
    opponents: [{ seat: "east", discards: ["1p", "4m"], openMelds: 1 }],
  });
  const actions = [
    { id: "pon_4m", action: "pon" as const, tile: "4m" as const, consumedTiles: ["4m", "4m"] as any },
    { id: "pass" as const, action: "pass" as const },
  ];
  const request = buildJevReactionRequest(reaction, actions, "test-model") as any;
  assert.deepEqual(request.state.pendingDiscard, { tile: "4m", fromSeat: "east" });
  assert.deepEqual(request.state.doraIndicators, ["3s"]);
  assert.deepEqual(Object.keys(request.questions.action.criteria), ["pon_4m", "pass"]);
});

test("Jev adapter normalizes display-rounded probabilities", async () => {
  const candidates = deterministicAdvice(state).candidates;
  const server = createServer((request, response) => {
    let body = "";
    request.on("data", (chunk) => { body += chunk; });
    request.on("end", () => {
      const ids = Object.keys(JSON.parse(body).questions.action.criteria);
      const probabilities = Object.fromEntries(ids.map((id: string, index: number) => [id, index === 0 ? 0.98 : index === 1 ? 0.01 : 0]));
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({
        model: "jev-test",
        answers: { action: { type: "choice", choice: ids[0], confidence: 0.8, probabilities } },
      }));
    });
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  try {
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("Test server failed");
    const result = await new JevClient("test-key", `http://127.0.0.1:${address.port}`, "jev-test").chooseDiscard(state, candidates);
    const total = Object.values(result.probabilities).reduce((sum, value) => sum + value, 0);
    assert.ok(Math.abs(total - 1) < 1e-12);
    assert.equal(result.actionId, candidates[0]!.actionId);
  } finally {
    server.close();
  }
});
