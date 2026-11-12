"""Experimental self-turn proof, scoped to CPU friend 300+0 only.

This helper does not grant permission to click. The caller must verify the
room, action deadline, exact hand, draw-only plan, and operation priority.
"""
import io
from PIL import Image, ImageChops, ImageStat

def self_turn_stability(before, after, report):
    try:
        with Image.open(io.BytesIO(before)) as aa, Image.open(io.BytesIO(after)) as bb:
            a,b=aa.convert('RGB'),bb.convert('RGB')
        if a.size != (1920,1080) or b.size != a.size: return False
        def self_lamp(image):
            pixels=image.crop((904,496,1016,516)).getdata()
            return sum(r>180 and g>110 and blue<170 for r,g,blue in pixels)
        if min(self_lamp(a),self_lamp(b)) < 1000: return False
        draw=report['handGeometry']['value']['drawSlot']
        x,y,w,h=(draw[k] for k in ('x','y','width','height'))
        if any(type(v) not in (int,float) for v in (x,y,w,h)) or not (1480 <= x <= 1490 and 918 <= y <= 924 and 88 <= w <= 100 and 140 <= h <= 158):
            return False
        # An already lifted tile can be discarded on the first click, which
        # bypasses selection confirmation. Refuse any bright surface above
        # the draw slot in either frame; overlays also fail closed.
        box=(int(x+10),int(y-41),int(x+w-10),int(y-6))
        if any(sum(min(pixel)>160 for pixel in im.crop(box).getdata()) > 50 for im in (a,b)):
            return False
        # Opponent's tile backs have animated illumination. They do not affect
        # the identity of the self draw, whose rectangle and every hand face,
        # prompt, table center and all other pixels remain checked below.
        # Do not ignore a missing, shifted, or heavily altered wall. Bound
        # both the total luminance transitions and 16px local changes, as
        # well as RGB drift, before normalizing the area for the older guard.
        for box, rgb_limit, pixel_limit, block_limit in (((320,70,375,190),10,80,20),((170,190,375,620),2,70,10)):
            ca,cb=(im.crop(box) for im in (a,b))
            if max(ImageStat.Stat(ImageChops.difference(ca,cb)).mean)>rgb_limit: return False
            ma,mb=(im.convert('L').point(lambda value:255 if value<120 else 0) for im in (ca,cb))
            delta=ImageChops.difference(ma,mb)
            if delta.histogram()[255] > pixel_limit: return False
            for y in range(0,delta.height,16):
                for x in range(0,delta.width,16):
                    if delta.crop((x,y,min(x+16,delta.width),min(y+16,delta.height))).histogram()[255] > block_limit:
                        return False
            b.paste(ca,box[:2])
        # Both frames are already decoded RGB. Encoding and decoding them
        # again adds latency without changing their pixels or the checks.
        from auto_operator import _experimental_draw_glyph_stability_decoded
        return _experimental_draw_glyph_stability_decoded(a,b,report)
    except (OSError, ValueError, TypeError, KeyError):
        return False
