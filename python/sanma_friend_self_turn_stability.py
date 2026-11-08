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
        encoded=[]
        for image in (a,b):
            output=io.BytesIO();image.save(output,format='PNG');encoded.append(output.getvalue())
        from auto_operator import experimental_draw_glyph_stability
        return experimental_draw_glyph_stability(*encoded,report)
    except (OSError, ValueError, TypeError, KeyError):
        return False
