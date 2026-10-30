import type { HandLayoutProposal } from './handLayoutProposal.js';
import { knownOpenHandProposalFitsCalibratedRow } from './handLayoutProposal.js';
import type { ScreenLayout } from './layout.js';
import { measureSlotPresence } from './templateMatcher.js';

/** Unverified 14-slot geometry from raised positions 9/11 seen in one match. */
export async function recoverSanmaRaisedClosedHand(frame:Buffer,layout:ScreenLayout,rejected:HandLayoutProposal):Promise<HandLayoutProposal|undefined>{
 if(layout.viewport.width!==1920 || layout.viewport.height!==1080 || !layout.drawSlot || layout.handSlots.length!==13 || rejected.evidence.detectedTiles!==2 || knownOpenHandProposalFitsCalibratedRow(rejected,layout,4))return undefined;
 const xs=[223,317,412,507,602,697,792,887,981,1076,1171,1266,1361];
 if(layout.drawSlot.x!==1486 || layout.drawSlot.y!==921 || xs.some((x,i)=>layout.handSlots[i]?.x!==x || layout.handSlots[i]?.y!==921 || layout.handSlots[i]?.height!==151))return undefined;
 const slots=[...layout.handSlots,layout.drawSlot];
 const present=await measureSlotPresence(frame,slots);if(present.length!==14 || present.some(value=>value<0.45))return undefined;
 const raised=await measureSlotPresence(frame,slots.map(rect=>({...rect,y:rect.y-42,height:26})));
 const indexes=raised.flatMap((value,index)=>value>=0.6?[index]:[]);
 if(indexes.length!==1 || ![9,11].includes(indexes[0]!) || raised.some((value,index)=>index!==indexes[0] && value>=0.15))return undefined;
 const handSlots=layout.handSlots.map((rect,index)=>index===indexes[0]?{...rect,y:rect.y-48}:rect);
 return {...rejected,viewport:layout.viewport,handSlots,drawSlot:layout.drawSlot,confidence:0,requiresHoldoutValidation:true,
   evidence:{...rejected.evidence,detectedTiles:14},clickPoints:[...handSlots,layout.drawSlot].map(rect=>({x:rect.x+rect.width/2,y:rect.y+rect.height/2}))};
}
