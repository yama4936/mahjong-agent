import { calibratedOpenHandProposal, knownOpenHandProposalFitsCalibratedRow,
  resolveOpenDrawGap, type HandLayoutProposal } from "./handLayoutProposal.js";
import type { ScreenLayout } from "./layout.js";
import { measureSlotPresence } from "./templateMatcher.js";

/** Unverified geometry candidate for a raised separated draw after two calls. */
export async function recoverSanmaRaisedDrawAfterTwoCalls(frame: Buffer, layout: ScreenLayout,
  rejected: HandLayoutProposal): Promise<HandLayoutProposal | undefined> {
  if (layout.viewport.width !== 1920 || layout.viewport.height !== 1080 || !layout.drawSlot
      || layout.handSlots.length < 12 || rejected.evidence.detectedTiles !== 2
      || knownOpenHandProposalFitsCalibratedRow(rejected, layout, 4)) return undefined;
  const calibratedX = [223, 317, 412, 507, 602, 697, 792, 887, 981, 1076, 1171, 1266];
  if (layout.drawSlot.x !== 1486 || layout.drawSlot.y !== 921
      || calibratedX.some((x, i) => layout.handSlots[i]?.x !== x
        || layout.handSlots[i]?.y !== 921 || layout.handSlots[i]?.height !== 151)) return undefined;
  const base = await resolveOpenDrawGap(frame, layout, calibratedOpenHandProposal(layout, 2));
  // Only the separated draw position is supported by the saved images.
  if (base.drawSlot.x !== 917) return undefined;
  const slots = [...base.handSlots, base.drawSlot];
  const presence = await measureSlotPresence(frame, [...slots, layout.handSlots[8]!]);
  if (presence.length !== 9 || presence.slice(0, 8).some(value => value < 0.45)
      || presence[8]! >= 0.35) return undefined;
  const raised = await measureSlotPresence(frame, slots.map(rect => ({...rect, y:rect.y - 42, height:26})));
  if (raised.length !== 8 || raised[7]! < 0.6 || raised.slice(0, 7).some(value => value >= 0.15)) return undefined;
  const drawSlot = {...base.drawSlot, y:base.drawSlot.y - 48};
  return {...base, drawSlot, confidence:0, requiresHoldoutValidation:true,
    clickPoints:[...base.clickPoints.slice(0, -1), {x:drawSlot.x + drawSlot.width / 2, y:drawSlot.y + drawSlot.height / 2}]};
}
