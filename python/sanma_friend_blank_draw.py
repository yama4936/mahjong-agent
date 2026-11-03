"""Candidate physical blank draw only; never identifies the tile as white."""
import io, math
from PIL import Image


def blank_draw_candidate(frame, hand, geometry, draw):
    try:
        tiles,matches=hand['tiles'],hand['matches']; evidence=geometry['evidence'];slot=geometry['drawSlot']
        match=matches[-1];gc=geometry['confidence'];spread=evidence['rowBottomSpread'];gap=evidence['drawGap'];median=evidence['medianGap']
        if (hand.get('turnReady') is not True or len(tiles)!=14 or len(matches)!=14
            or tiles[-1]!='P' or match.get('tile')!='P'
            or type(match.get('confidence')) not in (int,float) or match.get('confidence')!=0
            or type(match.get('runnerUpConfidence')) not in (int,float) or match.get('runnerUpConfidence')!=0
            or draw.get('status')!='candidate' or draw.get('index')!=13 or draw.get('tile')!='P'
            or evidence.get('detectedTiles')!=14
            or not all(type(v) in (int,float) and math.isfinite(v) for v in (gc,spread,gap,median))
            or not .98<=gc<=1 or not 0<=spread<=2 or gap<median+10):return False
        x,y,w,h=(slot[k] for k in ('x','y','width','height'))
        if (any(type(v) is not int for v in (x,y,w,h)) or not 85<=w<=100 or not 140<=h<=160
                or x<0 or y<0 or x+w>1920 or y+h>1080):return False
        point=draw['point']
        if (not isinstance(point,dict) or set(point)!={'x','y'}
                or any(type(point[k]) not in (int,float) or not math.isfinite(point[k]) for k in ('x','y'))
                or abs(point['x']-(x+w/2))>2 or abs(point['y']-(y+h/2))>2):return False
        with Image.open(io.BytesIO(frame)) as source:
            if source.size!=(1920,1080):return False
            image=source.convert('RGB');pixels=list(image.crop((x+w//4,y+h//4,x+3*w//4,y+3*h//4)).getdata())
        return sum(min(p)>=170 and max(p)-min(p)<=35 for p in pixels)/len(pixels)>=.99
    except (KeyError,TypeError,ValueError,IndexError,OSError,ZeroDivisionError):return False
