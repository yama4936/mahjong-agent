"""Read-only comparison of consecutive left-seat pon observations.

This is a narrow experimental observation, not a proof of turn continuity,
not an input gate, and never authorizes an operation.
"""
import io
import math
from PIL import Image, ImageChops, ImageStat
import numpy as np
from pathlib import Path
from functools import lru_cache

# Fixed client geometry: self hand, table/round metadata, left offered tile.
REGIONS = ((220,925,1455,1072), (870,355,1030,495), (707,292,775,333),
           (22,40,304,130),       # dora indicators
           (680,370,780,550),    # left river outside offered-tile halo
           (850,240,1125,312),   # opposite river
           (768,544,1140,754),   # own river
           (790,335,825,365),    # offered-tile neighbourhood
           (24,135,82,180))      # indicators beneath dora
WALL_REGION = (290,225,350,280)   # overlaps the animated left wall

@lru_cache(maxsize=16)
def _describe(data):
    with Image.open(io.BytesIO(data)) as source:
        if source.size != (1920,1080): raise ValueError('invalid image size')
        im=source.convert('RGB')
    green=np.asarray(im.crop((680,280,805,370)),dtype=np.int16)
    r,g,b=(green[:,:,i] for i in range(3))
    if np.count_nonzero((g>r+20)&(g>b+15)&(g>100))<100: return None
    with Image.open(Path(__file__).parent/'fixtures'/'sanma-pon-skip-156-row.png') as ref:
        reference=np.asarray(ref.convert('RGB').crop((0,0,824,90)),dtype=np.int16)
    row=np.asarray(im.crop((600,785,1424,875)),dtype=np.int16)
    delta=np.abs(row-reference).astype(np.int32);delta[72:80,816:824,:]=0
    if delta.mean(axis=(0,1)).max()>.1:return None
    ys=np.arange(0,90,8);xs=np.arange(0,824,8)
    blocks=np.add.reduceat(np.add.reduceat(delta,ys,axis=0),xs,axis=1)
    areas=np.minimum(8,90-ys)[:,None]*np.minimum(8,824-xs)[None,:]
    if (blocks/areas[:,:,None]).max()>10:return None
    return tuple(np.asarray(im.crop(box),dtype=np.int16) for box in (*REGIONS,WALL_REGION))

def _report_is_pon(report):
    try:
        row=report['buttonRow'];value=row['value'];slots=value['slots']
        return (row['status']=='candidate' and value['ronReferenceCompared'] is True
                and len(slots)==3 and [s['slot'] for s in slots]==[0,1,2]
                and slots[0]['status']=='empty_candidate'
                and slots[1]['status']=='candidate' and slots[1]['action']=='pon'
                and slots[2]['status']=='candidate' and slots[2]['action']=='skip'
                and all(type(s['confidence']) in (int,float) and .99 <= s['confidence'] <= 1 for s in slots))
    except (TypeError, KeyError, IndexError):
        return False

def compare_sequence(samples, report):
    """Require 3 ordered fresh observations of the same visible pon hypothesis.

    Each sample is {frame: bytes, sequence: int, capturedAt: monotonic seconds}.
    The caller owns trustworthy capture provenance. Return only descriptive data.
    """
    result={'status':'rejected','scope':'offline_untrusted_pon_sequence',
            'confirmed':False,'operationAuthorized':False}
    try:
        if not _report_is_pon(report) or len(samples)!=3: return result
        seq=[s['sequence'] for s in samples]; times=[s['capturedAt'] for s in samples]
        if (any(type(v) is not int for v in seq) or not seq[0]<seq[1]<seq[2]
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in times)
                or not times[0]<times[1]<times[2] or times[2]-times[0]>20): return result
        descriptors=[_describe(s['frame']) for s in samples]
        if any(x is None for x in descriptors):return result
        for current in descriptors[1:]:
            for a,b in zip(descriptors[0][:-1],current[:-1]):
                d=np.abs(a-b).astype(np.int32)
                if d.mean(axis=(0,1)).max()>4:return result
                h,w=d.shape[:2];ys=np.arange(0,h,16);xs=np.arange(0,w,16)
                blocks=np.add.reduceat(np.add.reduceat(d,ys,axis=0),xs,axis=1)
                areas=np.minimum(16,h-ys)[:,None]*np.minimum(16,w-xs)[None,:]
                if (blocks/areas[:,:,None]).max()>20:return result
            # The upper-left corner overlaps animated backs. Compare broad
            # luminance structure rather than RGB lighting there.
            a,b=descriptors[0][-1],current[-1]
            def dark(im):
                im=im.astype(np.int32)
                return ((im[:,:,0]*299+im[:,:,1]*587+im[:,:,2]*114)//1000)<120
            delta=dark(a)!=dark(b)
            if np.count_nonzero(delta)>60:return result
            h,w=delta.shape
            if any(np.count_nonzero(delta[y:y+16,x:x+16])>14
                   for y in range(0,h,16) for x in range(0,w,16)):return result
        result.update(status='candidate', firstSequence=seq[0], lastSequence=seq[-1],
                      durationMs=round((times[-1]-times[0])*1000),
                      limitations=['capture provenance and uninterrupted interval unverified',
                                   'fixed left-offer geometry; time and actions unverified'])
        return result
    except (OSError,TypeError,ValueError,KeyError,IndexError):
        return result
