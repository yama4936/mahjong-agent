import { chromium, type Browser, type BrowserContext, type Page } from "playwright";
import { writeFile } from "node:fs/promises";
import sharp from "sharp";
import type { ScreenLayout } from "../recognition/layout.js";
import type { DecisionResult } from "../agent/decision.js";
import type { ActionButton } from "../recognition/actionButtonRecognizer.js";

export interface ActionExecutionReceipt {
  action: "discard";
  tileIndex: number;
  clickPoint: { x: number; y: number };
  clickedAt: string;
  confirmedAt: string;
  confirmation: "hand_and_own_river_changed";
  confirmationLatencyMs: number;
}

export interface UiActionExecutionReceipt {
  action: ActionButton;
  clickPoint: { x: number; y: number };
  clickedAt: string;
  confirmedAt: string;
  confirmation: "action_button_region_changed" | "action_button_hand_and_meld_changed";
  confirmationLatencyMs: number;
}

export interface JantamaSession {
  browser: Browser;
  context: BrowserContext;
  page: Page;
}

export async function connectJantama(cdpUrl: string): Promise<JantamaSession> {
  const browser = await chromium.connectOverCDP(cdpUrl);
  const context = browser.contexts()[0];
  if (!context) throw new Error("No browser context exposed by CDP");
  const page = context.pages().find((candidate) => candidate.url().includes("mahjongsoul.com"));
  if (!page) throw new Error("No Mahjong Soul page found in the connected browser");
  return { browser, context, page };
}

export async function captureStableFrame(page: Page, outputPath: string, layout: ScreenLayout): Promise<void> {
  const image = await captureViewport(page, layout);
  await writeFile(outputPath, image, { mode: 0o600 });
}

export async function captureViewport(page: Page, layout: ScreenLayout): Promise<Buffer> {
  const image = await page.screenshot({ animations: "disabled" });
  const metadata = await sharp(image).metadata();
  if (metadata.width !== layout.viewport.width || metadata.height !== layout.viewport.height) {
    throw new Error(`Viewport mismatch: expected ${layout.viewport.width}x${layout.viewport.height}, got ${metadata.width ?? 0}x${metadata.height ?? 0}`);
  }
  return image;
}

export async function guardedDiscard(
  page: Page,
  layout: ScreenLayout,
  tileIndex: number,
  safety: { allowed: boolean; recognitionConfidence: number; decisionConfidence: number },
): Promise<ActionExecutionReceipt> {
  if (!safety.allowed) throw new Error("Safety gate rejected automatic operation");
  if (safety.recognitionConfidence < layout.minimumTileConfidence) throw new Error("Recognition confidence is below threshold");
  if (safety.decisionConfidence < 0.55) throw new Error("Decision confidence is below threshold");
  if (!layout.autoOperation) throw new Error("Auto operation is not enabled by a passing template calibration");
  const point = layout.clickPoints[tileIndex];
  if (!point) throw new Error(`No click point for hand index ${tileIndex}`);
  const slots = layout.drawSlot ? [...layout.handSlots, layout.drawSlot] : layout.handSlots;
  const left = Math.min(...slots.map((slot) => slot.x));
  const top = Math.min(...slots.map((slot) => slot.y));
  const right = Math.max(...slots.map((slot) => slot.x + slot.width));
  const bottom = Math.max(...slots.map((slot) => slot.y + slot.height));
  const clip = { x: left, y: top, width: right - left, height: bottom - top };
  const ownRiver = layout.publicTileRegions?.ownDiscards;
  if (!ownRiver) throw new Error("Own discard region is required for post-click verification");
  const riverClip = { x: ownRiver.x, y: ownRiver.y, width: ownRiver.width, height: ownRiver.height };
  const before = await page.screenshot({ clip, animations: "disabled" });
  const riverBefore = await page.screenshot({ clip: riverClip, animations: "disabled" });
  await page.waitForTimeout(120);
  const after = await page.screenshot({ clip, animations: "disabled" });
  if (!before.equals(after)) throw new Error("Hand changed during pre-click stability check");
  const clickedAt = new Date();
  await page.mouse.click(point.x, point.y);
  const deadline = Date.now() + 2_500;
  while (Date.now() < deadline) {
    await page.waitForTimeout(100);
    const [handAfter, riverAfter] = await Promise.all([
      page.screenshot({ clip, animations: "disabled" }),
      page.screenshot({ clip: riverClip, animations: "disabled" }),
    ]);
    if (!before.equals(handAfter) && !riverBefore.equals(riverAfter)) {
      const confirmedAt = new Date();
      return {
        action: "discard",
        tileIndex,
        clickPoint: point,
        clickedAt: clickedAt.toISOString(),
        confirmedAt: confirmedAt.toISOString(),
        confirmation: "hand_and_own_river_changed",
        confirmationLatencyMs: confirmedAt.getTime() - clickedAt.getTime(),
      };
    }
  }
  throw new Error("Automatic discard was not confirmed by both hand and own-river changes");
}

/**
 * Non-discard actions remain impossible until that exact button has its own
 * perfect holdout certificate. Certificates are action-specific so a passing
 * discard recognizer can never unlock chi/pon/kan/ron clicks.
 */
export async function guardedUiAction(
  page: Page,
  layout: ScreenLayout,
  action: ActionButton,
  safety: {
    allowed: boolean;
    buttonConfidence: number;
    decisionConfidence: number;
    templateSetFingerprint: string;
  },
): Promise<UiActionExecutionReceipt> {
  if (!safety.allowed) throw new Error("Safety gate rejected automatic UI action");
  if (safety.buttonConfidence < 0.98) throw new Error("Action button confidence is below threshold");
  if (safety.decisionConfidence < 0.55) throw new Error("Decision confidence is below threshold");
  const region = layout.actionButtonRegions?.[action];
  if (!region) throw new Error(`No calibrated region for ${action}`);
  const certificate = layout.actionOperation?.[action];
  if (!certificate?.enabled) throw new Error(`${action} click is forbidden without an action-specific calibration certificate`);
  if (certificate.templateSetFingerprint !== safety.templateSetFingerprint) {
    throw new Error(`${action} template set does not match its calibration certificate`);
  }
  const clip = { x: region.x, y: region.y, width: region.width, height: region.height };
  const before = await page.screenshot({ clip, animations: "disabled" });
  const isCall = action === "chi" || action === "pon" || action === "kan";
  const handSlots = layout.drawSlot ? [...layout.handSlots, layout.drawSlot] : layout.handSlots;
  const handClip = {
    x: Math.min(...handSlots.map((slot) => slot.x)),
    y: Math.min(...handSlots.map((slot) => slot.y)),
    width: Math.max(...handSlots.map((slot) => slot.x + slot.width)) - Math.min(...handSlots.map((slot) => slot.x)),
    height: Math.max(...handSlots.map((slot) => slot.y + slot.height)) - Math.min(...handSlots.map((slot) => slot.y)),
  };
  const meldRegion = layout.publicTileRegions?.ownMelds;
  if (isCall && !meldRegion) throw new Error(`Own meld region is required to verify ${action}`);
  const meldClip = meldRegion ? { x: meldRegion.x, y: meldRegion.y, width: meldRegion.width, height: meldRegion.height } : undefined;
  const handBefore = isCall ? await page.screenshot({ clip: handClip, animations: "disabled" }) : undefined;
  const meldBefore = isCall && meldClip ? await page.screenshot({ clip: meldClip, animations: "disabled" }) : undefined;
  await page.waitForTimeout(120);
  if (!before.equals(await page.screenshot({ clip, animations: "disabled" }))) {
    throw new Error("Action button changed during pre-click stability check");
  }
  const point = { x: region.x + region.width / 2, y: region.y + region.height / 2 };
  const clickedAt = new Date();
  await page.mouse.click(point.x, point.y);
  const deadline = Date.now() + 2_500;
  while (Date.now() < deadline) {
    await page.waitForTimeout(100);
    const buttonChanged = !before.equals(await page.screenshot({ clip, animations: "disabled" }));
    const callChanged = !isCall || Boolean(
      handBefore && meldBefore && meldClip
      && !handBefore.equals(await page.screenshot({ clip: handClip, animations: "disabled" }))
      && !meldBefore.equals(await page.screenshot({ clip: meldClip, animations: "disabled" })),
    );
    if (buttonChanged && callChanged) {
      const confirmedAt = new Date();
      return {
        action,
        clickPoint: point,
        clickedAt: clickedAt.toISOString(),
        confirmedAt: confirmedAt.toISOString(),
        confirmation: isCall ? "action_button_hand_and_meld_changed" : "action_button_region_changed",
        confirmationLatencyMs: confirmedAt.getTime() - clickedAt.getTime(),
      };
    }
  }
  throw new Error(`${action} click was not confirmed by the required UI state changes`);
}

export async function showAdvisorOverlay(page: Page, decision: DecisionResult): Promise<void> {
  const tileName = (tile: string) => {
    const honors: Record<string, string> = { E: "東", S: "南", W: "西", N: "北", P: "白", F: "發", C: "中" };
    if (honors[tile]) return honors[tile];
    const match = tile.match(/^([0-9])([mps])$/);
    if (!match) return tile;
    const rank = match[1] === "0" ? "赤5" : match[1];
    const suit: Record<string, string> = { m: "萬", p: "筒", s: "索" };
    return `${rank}${suit[match[2]!]}`;
  };
  const actionNames: Record<string, string> = {
    discard: "打牌", riichi: "リーチ", tsumo: "ツモ", ron: "ロン", kyuushu: "九種九牌",
    chi: "チー", pon: "ポン", minkan: "明槓", ankan: "暗槓", kakan: "加槓", pass: "見送り",
  };
  const reasonNames: Record<string, string> = {
    recognition_confidence_below_threshold: "牌認識の信頼度が基準未満",
    public_state_confidence_below_threshold: "局面認識の信頼度が基準未満",
    jev_confidence_below_threshold: "Jev判断の信頼度が基準未満",
    jev_required_for_auto_mode: "自動モードにはJevが必要",
    no_legal_action: "合法な候補なし",
    candidate_not_in_hand: "候補牌が手牌にない",
    ambiguous_call_variant: "鳴き候補を特定できない",
  };
  const ordered = [
    ...decision.candidates.filter((candidate) => candidate.actionId === decision.selectedActionId),
    ...decision.candidates.filter((candidate) => candidate.actionId !== decision.selectedActionId),
  ];
  const top = ordered.slice(0, 3).map((candidate) => ({
    label: tileName(candidate.tile),
    detail: `${candidate.shanten}向聴 / 受入${candidate.ukeire}枚 / EV ${candidate.expectedRoundValue ?? "-"} / 放銃リスク ${candidate.dealInProbability === undefined ? "-" : `${(candidate.dealInProbability * 100).toFixed(1)}%`}`,
    selected: candidate.actionId === decision.selectedActionId,
  }));
  const localizeReason = (reason: string) => reason.startsWith("jev_error:")
    ? `Jevエラー: ${reason.slice("jev_error:".length)}`
    : reasonNames[reason] ?? reason;
  const safeText = decision.safety.allowed
    ? "安全基準を通過"
    : `停止: ${decision.safety.reasons.map(localizeReason).join("、")}`;
  const action = decision.selectedAction.action;
  const actionText = `${actionNames[action] ?? action}${"tile" in decision.selectedAction ? ` ${tileName(decision.selectedAction.tile)}` : ""}`;
  const reactionActions = new Set(["ron", "chi", "pon", "minkan", "pass"]);
  const reactionRows = reactionActions.has(action)
    ? [
        ...decision.legalActions.filter((candidate) => candidate.id === decision.selectedActionId),
        ...decision.legalActions.filter((candidate) => candidate.id !== decision.selectedActionId),
      ].map((candidate) => ({
        label: `${actionNames[candidate.action] ?? candidate.action}${"tile" in candidate ? ` ${tileName(candidate.tile)}` : ""}`,
        detail: decision.jev?.probabilities[candidate.id] === undefined
          ? "選択確率 —"
          : `選択確率 ${(decision.jev.probabilities[candidate.id]! * 100).toFixed(1)}%`,
        selected: candidate.id === decision.selectedActionId,
      }))
    : top;
  const modeName = decision.mode === "advisor" ? "助言モード" : decision.mode === "observer" ? "監視モード" : "自動モード";
  await page.evaluate(({ decision, rows, safeText, actionText, modeName }) => {
    const id = "jantama-auto-advisor";
    document.getElementById(id)?.remove();
    const root = document.createElement("aside");
    root.id = id;
    root.setAttribute("aria-label", "麻雀打牌アドバイザー");
    root.style.cssText = [
      "position:fixed", "z-index:2147483647", "top:18px", "left:18px", "width:380px",
      "padding:16px", "border:1px solid rgba(232,190,90,.8)", "border-radius:12px",
      "background:rgba(10,14,20,.92)", "color:#f6f0dc", "font:14px/1.45 system-ui,sans-serif",
      "box-shadow:0 8px 30px rgba(0,0,0,.45)", "pointer-events:none",
    ].join(";");
    const rowHtml = rows.map((item) => `<div style="display:grid;grid-template-columns:110px 1fr;gap:10px;opacity:${item.selected ? 1 : .72}"><span style="font-weight:${item.selected ? 750 : 500}">${item.selected ? "→ " : ""}${item.label}</span><span style="text-align:right;white-space:nowrap">${item.detail}</span></div>`).join("");
    root.innerHTML = `<div style="color:#d9b85f;font-size:12px">${modeName} · ${decision.source}</div><div style="font-size:28px;font-weight:750;margin:4px 0 8px">${actionText}</div><div style="margin-bottom:10px">信頼度 ${(decision.confidence * 100).toFixed(1)}% · ${safeText}</div>${rowHtml ? `<div style="border-top:1px solid rgba(255,255,255,.18);padding-top:8px">${rowHtml}</div>` : ""}`;
    document.body.append(root);
  }, { decision: { source: decision.source, confidence: decision.confidence }, rows: reactionRows, safeText, actionText, modeName });
}

export async function hideAdvisorOverlay(page: Page): Promise<void> {
  await page.evaluate(() => document.getElementById("jantama-auto-advisor")?.remove());
}
