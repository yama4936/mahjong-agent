import { calibratedOpenHandProposal, knownOpenHandProposalFitsCalibratedRow,
  resolveOpenDrawGap, type HandLayoutProposal } from "./handLayoutProposal.js";
import type { ScreenLayout } from "./layout.js";
import { measureSlotPresence } from "./templateMatcher.js";

/** Unverified five-tile geometry, only for the two raised positions seen in one match. */
export async function recoverSanmaRaisedFive(frame: Buffer, layout: ScreenLayout,
  rejected: HandLayoutProposal): Promise<HandLayoutProposal | undefined> {
  if (layout.viewport.width !== 1920 || layout.viewport.height !== 1080 || !layout.drawSlot
      || layout.handSlots.length < 12 || rejected.evidence.detectedTiles !== 2
      || knownOpenHandProposalFitsCalibratedRow(rejected, layout, 4)) return undefined;
  const xs = [223, 317, 412, 507, 602, 697, 792, 887, 981, 1076, 1171, 1266];
  if (layout.drawSlot.x !== 1486 || layout.drawSlot.y !== 921 || xs.some((x, i) =>
    layout.handSlots[i]?.x !== x || layout.handSlots[i]?.y !== 921 || layout.handSlots[i]?.height !== 151)) return undefined;
  const base = await resolveOpenDrawGap(frame, layout, calibratedOpenHandProposal(layout, 3));
  if (base.drawSlot.x !== 632) return undefined;
  const slots = [...base.handSlots, base.drawSlot];
  const present = await measureSlotPresence(frame, [...slots, layout.handSlots[5]!]);
  if (present.length !== 6 || present.slice(0,5).some(value => value < 0.45) || present[5]! >= 0.35) return undefined;
  const raised = await measureSlotPresence(frame, slots.map(rect => ({...rect, y:rect.y-42, height:26})));
  const indexes = raised.flatMap((value, index) => value >= 0.6 ? [index] : []);
  if (indexes.length !== 1 || ![0,4].includes(indexes[0]!) || raised.some((value,index) => index !== indexes[0] && value >= 0.15)) return undefined;
  const corrected = slots.map((rect,index) => index === indexes[0] ? {...rect,y:rect.y-48} : rect);
  return {...base, handSlots:corrected.slice(0,4), drawSlot:corrected[4]!, confidence:0, requiresHoldoutValidation:true,
    clickPoints:corrected.map(rect=>({x:rect.x+rect.width/2,y:rect.y+rect.height/2}))};
}
