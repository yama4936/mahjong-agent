import type { HandLayoutProposal } from './handLayoutProposal.js';
import type { ScreenLayout } from './layout.js';
import { measureSlotPresence } from './templateMatcher.js';

/** Untrusted geometry only for a raised draw in the documented native layout. */
export async function recoverSanmaRaisedClosedDraw(frame:Buffer,layout:ScreenLayout):Promise<HandLayoutProposal|undefined>{
 if(layout.viewport.width!==1920 || layout.viewport.height!==1080 || !layout.drawSlot || layout.handSlots.length!==13)return undefined;
 const xs=[223,317,412,507,602,697,792,887,981,1076,1171,1266,1361];
 if(layout.drawSlot.x!==1486 || layout.drawSlot.y!==921 || xs.some((x,i)=>layout.handSlots[i]?.x!==x || layout.handSlots[i]?.y!==921 || layout.handSlots[i]?.height!==151))return undefined;
 const slots=[...layout.handSlots,layout.drawSlot],presence=await measureSlotPresence(frame,slots);
 if(presence.length!==14 || presence.some(value=>value<0.45))return undefined;
 const raised=await measureSlotPresence(frame,slots.map(r=>({...r,y:r.y-42,height:26})));
 if(raised.length!==14 || raised[13]!<0.6 || raised.slice(0,13).some(value=>value>=0.15))return undefined;
 const drawSlot={...layout.drawSlot,y:layout.drawSlot.y-48};
 return {viewport:layout.viewport,handSlots:layout.handSlots,drawSlot,confidence:0,requiresHoldoutValidation:true,
   // -1 denotes unavailable detector evidence; these values are not counts.
   evidence:{detectedTiles:-1,luminanceThreshold:-1,medianWidth:-1,medianHeight:-1,medianGap:-1,drawGap:-1,rowBottomSpread:-1},
   clickPoints:[...layout.handSlots,drawSlot].map(r=>({x:r.x+r.width/2,y:r.y+r.height/2}))};
}
