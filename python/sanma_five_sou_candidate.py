"""Narrow, image-only ordinary 5s hypothesis for reviewed CPU friend experiments.

This is not an independent turn, legality, or game-state check.  It is a
second visual check on a tile label selected by the normal recognizer.
"""
import io
import math
from PIL import Image


def ordinary_five_sou_candidate(frame, hand, geometry, draw):
    try:
        tiles, matches = hand['tiles'], hand['matches']
        match, slot = matches[-1], geometry['drawSlot']
        evidence = geometry['evidence']
        confidence, runner = match['confidence'], match['runnerUpConfidence']
        gc = geometry.get('confidence')
        spread, gap, median = (evidence.get(k) for k in ('rowBottomSpread', 'drawGap', 'medianGap'))
        if (hand.get('turnReady') is not True or len(tiles) != 14 or len(matches) != 14
            or draw.get('index') != 13 or draw.get('tile') != '5s' or tiles[-1] != '5s'
            or match.get('tile') != '5s' or not all(type(x) in (int, float) and math.isfinite(x) for x in (confidence, runner))
            or not .96 <= confidence <= 1 or not 0 <= runner <= 1 or confidence-runner < .1
            or not all(type(x) in (int, float) and math.isfinite(x) for x in (gc, spread, gap, median))
            or evidence.get('detectedTiles') != 14 or not .98 <= gc <= 1
            or gap < median + 10 or not 0 <= spread <= 2):
            return False
        x,y,w,h=(slot[k] for k in ('x','y','width','height'))
        if any(type(v) is not int for v in (x,y,w,h)) or not (0 <= x and 0 <= y and 70 <= w <= 110 and 120 <= h <= 180 and x+w <= 1920 and y+h <= 1080):
            return False
        with Image.open(io.BytesIO(frame)) as source:
            if source.size != (1920, 1080): return False
            image=source.convert('RGB').crop((x,y,x+w,y+h)).resize((93,151))
        def green(v):
            r,g,b=v
            return g>r*1.25 and g>b*1.1 and g>35
        def red(v):
            r,g,b=v
            return r>g*1.4 and r>b*1.3 and r>55
        def bands(x0,x1):
            out=[]; start=None
            for y in range(20,136):
                hit=y<135 and sum(green(image.getpixel((x,y))) for x in range(x0,x1)) >= 3
                if hit and start is None: start=y
                if not hit and start is not None:
                    out.append((start,y-1)); start=None
            return out
        for x0,x1 in ((6,35),(58,87)):
            segments=bands(x0,x1)
            if (len(segments)!=2 or any(b-a+1<35 for a,b in segments)
                or not 25<=segments[0][0]<=40 or not 82<=segments[1][0]<=100):
                return False
        core=[image.getpixel((x,y)) for y in range(45,108) for x in range(33,60)]
        return sum(map(red,core)) >= 250 and sum(map(green,core)) <= 40
    except (KeyError,TypeError,ValueError,IndexError,OSError):
        return False
