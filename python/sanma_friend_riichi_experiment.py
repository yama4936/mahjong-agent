"""Experimental friend-only declaration with a single visible legal discard."""
import io
import time
from pathlib import Path
from PIL import Image
from auto_operator import crop_screenshot, clip_for_hand, riichi_selection_is_visible, send_discard_click
from sanma_friend_freshness import friend_frame_stable, friend_action_started_at
from sanma_friend_pass_experiment import execute_friend_pon_pass


def unique_riichi_selection(frame, layout):
    """Return one visually bright slot only; does not establish tile identity."""
    try:
        slots = [*layout['handSlots'],layout['drawSlot']]
        if len(slots)!=14 or len(layout['clickPoints'])!=14 or not riichi_selection_is_visible(crop_screenshot(frame,clip_for_hand(layout))): return None
        with Image.open(io.BytesIO(frame)) as source:
            if source.size != (1920,1080): return None
            image=source.convert('RGB'); bright=[]
            for i,slot in enumerate(slots):
                x,y,w,h=(slot[k] for k in ('x','y','width','height'))
                if any(type(v) is not int for v in (x,y,w,h)) or not (85<=w<=100 and 140<=h<=160) or x<0 or y<0 or x+w>1920 or y+h>1080:return None
                pixels=list(image.crop((x+10,y+10,x+w-10,y+h-38)).getdata());n=len(pixels)
                light=sum(min(p)>180 and max(p)-min(p)<60 for p in pixels)/n
                dim=sum(60<=min(p)<=160 and max(p)-min(p)<25 for p in pixels)/n
                if light>=.4 and dim<.05: bright.append(i)
                elif dim<.45 or light>=.05:return None
            return bright[0] if len(bright)==1 else None
    except (OSError,TypeError,ValueError,KeyError,IndexError,ZeroDivisionError):
        return None


def execute_friend_riichi(operator, page, receipt):
    """Declare on a unique prompt; stop unless the client shows one legal discard.

    This baseline declares whenever eligible and does not evaluate expected
    value, furiten, or defense. The subsequent result remains unverified.
    """
    execute_friend_pon_pass(operator,page,receipt,declare_riichi=True)
    page.wait_for_timeout(500)
    selection=page.screenshot(animations='disabled')
    index=unique_riichi_selection(selection,operator.layout)
    path=operator.frames / f'riichi-selection-{time.time_ns()}.png';path.write_bytes(selection)
    operator.log('sanma_friend_riichi_selection',screenshot=str(path),candidateIndex=index,confirmed=False)
    if index is None: raise RuntimeError('riichi selection is not uniquely visible')
    page.wait_for_timeout(200)
    fresh=page.screenshot(animations='disabled')
    if not friend_frame_stable(selection,fresh) or unique_riichi_selection(fresh,operator.layout)!=index:
        raise RuntimeError('riichi selection changed before discard')
    started=friend_action_started_at(operator)
    def deadline():
        if operator.verified_friend_300_active is not True or type(started) not in (float,int) or not 0<=time.monotonic()-started<300:
            raise RuntimeError('friend session revoked or action deadline expired')
    deadline();point=operator.layout['clickPoints'][index]
    result=send_discard_click(page.mouse,point,operator.layout['viewport'],page.wait_for_timeout,fresh,
                              lambda _:page.screenshot(animations='disabled'),operator.layout,index,5,deadline)
    operator.log('sanma_friend_riichi_discard_attempted',index=index,point=point,selection=result,confirmed=False)
    return {'clicked':True,'action':'riichi_discard','confirmation':'unknown','stopped':True}
