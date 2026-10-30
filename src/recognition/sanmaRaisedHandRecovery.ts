import { calibratedOpenHandProposal, knownOpenHandProposalFitsCalibratedRow,
  resolveOpenDrawGap, type HandLayoutProposal } from "./handLayoutProposal.js";
import type { ScreenLayout } from "./layout.js";
import { measureSlotPresence } from "./templateMatcher.js";

/**
 * Offline candidate only, calibrated to one raised 11-tile row. No output is
 * proof of hand size, open melds, drawn tile, labels, or click coordinates.
 */
export async function recoverSanmaRaisedHand(frame: Buffer, layout: ScreenLayout,
  rejected: HandLayoutProposal): Promise<HandLayoutProposal | undefined> {
  if (layout.viewport.width !== 1920 || layout.viewport.height !== 1080 || !layout.drawSlot
      || layout.handSlots.length < 12 || rejected.evidence.detectedTiles !== 2
      || knownOpenHandProposalFitsCalibratedRow(rejected, layout, 4)) return undefined;
  const calibratedX = [223, 317, 412, 507, 602, 697, 792, 887, 981, 1076, 1171, 1266];
  if (layout.drawSlot.x !== 1486 || layout.drawSlot.y !== 921
      || calibratedX.some((x, index) => layout.handSlots[index]?.x !== x
        || layout.handSlots[index]?.y !== 921 || layout.handSlots[index]?.height !== 151)) return undefined;
  const base = await resolveOpenDrawGap(frame, layout, calibratedOpenHandProposal(layout, 1));
  const normal = [...base.handSlots, base.drawSlot];
  const extra = layout.handSlots[11]!;
  const presence = await measureSlotPresence(frame, [...normal, extra]);
  if (presence.length !== 12 || presence.slice(0, 11).some(value => value < 0.45)
      || presence[11]! >= 0.35) return undefined;
  const raisedBands = base.handSlots.map(rect => ({ ...rect, y: rect.y - 42, height: 26 }));
  const raised = await measureSlotPresence(frame, raisedBands);
  const indexes = raised.flatMap((value, index) => value >= 0.6 ? [index] : []);
  if (indexes.length !== 1 || raised.some((value, index) => index !== indexes[0] && value >= 0.15)) return undefined;
  const handSlots = base.handSlots.map((rect, index) => index === indexes[0]
    ? { ...rect, y: rect.y - 48 } : rect);
  const rects = [...handSlots, base.drawSlot];
  return { ...base, handSlots, confidence: 0,
    clickPoints: rects.map(rect => ({ x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 })),
    requiresHoldoutValidation: true };
}
