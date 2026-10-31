"""Experimental friend-only declaration with a single visible legal discard."""
import io
import math
import time
from pathlib import Path
from PIL import Image
from auto_operator import crop_screenshot, clip_for_hand, riichi_selection_is_visible, send_discard_click, tile_face_structure_delta
from sanma_friend_freshness import friend_frame_stable, friend_action_started_at
from sanma_friend_pass_experiment import execute_friend_pon_pass


def riichi_bright_slots(frame, layout):
    """Return visually bright slots; does not establish tile identity."""
    try:
        slots = [*layout['handSlots'],layout['drawSlot']]
        if (len(slots)!=14 or len(layout['clickPoints'])!=14
                or layout.get('viewport') != {'width':1920,'height':1080}
                or not riichi_selection_is_visible(crop_screenshot(frame,clip_for_hand(layout)))): return None
        with Image.open(io.BytesIO(frame)) as source:
            if source.size != (1920,1080): return None
            image=source.convert('RGB'); bright=[]
            for i,slot in enumerate(slots):
                x,y,w,h=(slot[k] for k in ('x','y','width','height'))
                if any(type(v) is not int for v in (x,y,w,h)) or not (85<=w<=100 and 140<=h<=160) or x<0 or y<0 or x+w>1920 or y+h>1080:return None
                point=layout['clickPoints'][i]
                if (not isinstance(point,dict) or set(point) != {'x','y'}
                        or any(type(point[k]) not in (int,float) or not math.isfinite(point[k]) for k in ('x','y'))
                        or abs(point['x']-(x+w/2))>2 or abs(point['y']-(y+h/2))>2):return None
                if i and slots[i-1]['x']+slots[i-1]['width'] > x:return None
                pixels=list(image.crop((x+10,y+10,x+w-10,y+h-38)).getdata());n=len(pixels)
                light=sum(min(p)>180 and max(p)-min(p)<60 for p in pixels)/n
                dim=sum(60<=min(p)<=160 and max(p)-min(p)<25 for p in pixels)/n
                if light>=.4 and dim<.35 and light>dim*1.5: bright.append(i)
                elif dim<.45 or light>=.05:return None
            return bright if bright else None
    except (OSError,TypeError,ValueError,KeyError,IndexError,ZeroDivisionError):
        return None


def unique_riichi_selection(frame, layout):
    slots = riichi_bright_slots(frame, layout)
    return slots[0] if slots is not None and len(slots) == 1 else None


def choose_riichi_selection(frame, layout, receipt):
    """Use the client's bright set; multi-option shape data stays unverified."""
    bright=riichi_bright_slots(frame,layout)
    if bright is None:return None
    if len(bright)==1:return bright[0]
    try:
        from sanma_friend_shape_candidate import friend_shape_candidate
        shape=friend_shape_candidate(receipt)
        if shape.get('status')!='candidate':return None
        report=receipt['sourceObservation']['report'];hand=report['hand']['value'];geometry=report['handGeometry']['value']
        slots=[*layout['handSlots'],layout['drawSlot']]
        if (geometry['handSlots']!=layout['handSlots'] or geometry['drawSlot']!=layout['drawSlot']
                or geometry['clickPoints']!=layout['clickPoints'] or len(hand['matches'])!=14
                or any(m.get('tile')!=t or type(m.get('confidence')) not in (int,float)
                       or type(m.get('runnerUpConfidence')) not in (int,float)
                       or not math.isfinite(m['confidence']) or not math.isfinite(m['runnerUpConfidence'])
                       or m['confidence']<.94 or m['confidence']-m['runnerUpConfidence']<.1
                       for t,m in zip(hand['tiles'],hand['matches']))): return None
        baseline=Path(receipt['screenshot']).read_bytes()
        import hashlib
        if hashlib.sha256(baseline).hexdigest()!=receipt['digest']:return None
        # The bright tiles must have the same physical face before and after
        # declaring; an animation, shifted slot or changed tile stops input.
        options=[];rows=receipt['structuralPositions']['candidates']
        for index in bright:
            slot=slots[index]
            face={'x':slot['x']+10,'y':slot['y']+10,'width':slot['width']-20,'height':slot['height']-38}
            if tile_face_structure_delta(crop_screenshot(baseline,face),crop_screenshot(frame,face))>.5:return None
            rows_for_tile=[r for r in rows if r['tile']==hand['tiles'][index]]
            if len(rows_for_tile)!=1 or rows_for_tile[0]['shanten']!=0:return None
            row=rows_for_tile[0]
            if not any(p['index']==index and p['point']==layout['clickPoints'][index] for p in row['positions']):return None
            options.append((row['shanten'],-row['maximumUnseenTotal'],index))
        return min(options)[2] if options else None
    except (OSError,KeyError,TypeError,ValueError,IndexError):return None


def execute_friend_riichi(operator, page, receipt):
    """Declare on a unique prompt; stop unless the client shows one legal discard.

    This baseline declares whenever eligible and does not evaluate expected
    value, furiten, or defense. The subsequent result remains unverified.
    """
    # Once attempted, suppress non-draw hand discards until a new round.
    operator.sanma_friend_riichi_attempted = True
    execute_friend_pon_pass(operator,page,receipt,declare_riichi=True)
    page.wait_for_timeout(500)
    selection=page.screenshot(animations='disabled')
    index=choose_riichi_selection(selection,operator.layout,receipt)
    path=operator.frames / f'riichi-selection-{time.time_ns()}.png';path.write_bytes(selection)
    bright=riichi_bright_slots(selection,operator.layout)
    evidence=None
    if index is not None and bright is not None and len(bright)>1:
        rows=receipt.get('structuralPositions',{}).get('candidates',[])
        evidence=[{'tile':row['tile'],'shanten':row['shanten'],'improvingDrawUpperBound':row['maximumUnseenTotal'],
                   'indices':[p['index'] for p in row['positions'] if p['index'] in bright]}
                  for row in rows if any(p['index'] in bright for p in row['positions'])]
    operator.log('sanma_friend_riichi_selection',screenshot=str(path),candidateIndex=index,
                 brightIndices=bright,shapeHypotheses=evidence,confirmed=False,
                 risk='recognized labels, live counts, furiten and value are unverified')
    if index is None: raise RuntimeError('riichi selection is ambiguous or unsupported')
    page.wait_for_timeout(200)
    fresh=page.screenshot(animations='disabled')
    if not friend_frame_stable(selection,fresh) or choose_riichi_selection(fresh,operator.layout,receipt)!=index:
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
