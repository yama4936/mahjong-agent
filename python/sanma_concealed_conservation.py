"""Image-level consistency check for a retained concealed hand.

This is supporting evidence only, not a tile identity or turn certificate.
"""
from collections import Counter
from itertools import permutations
from PIL import Image, ImageChops, ImageStat


def consistent(before, after, selected_index, limit=5.0):
    """Match each retained tile's glyph to the same candidate in later frame."""
    try:
        def parts(receipt):
            report = receipt['sourceObservation']['report']
            hand = report['hand']
            geometry = report['handGeometry']
            value = hand['value']
            if (hand['status'] != 'candidate' or geometry['status'] != 'candidate'
                    or value['candidateMelds'] != 0):
                raise ValueError('not closed candidate')
            tiles = value['tiles']
            g = geometry['value']
            slots = [*g['handSlots'], g['drawSlot']]
            if len(tiles) != 14 or len(slots) != 14:
                raise ValueError('bad hand size')
            with Image.open(receipt['screenshot']) as image:
                image = image.convert('RGB')
                if image.size != (1920, 1080):
                    raise ValueError('bad image dimensions')
                faces = []
                for slot in slots:
                    x,y,w,h = (int(slot[k]) for k in ('x','y','width','height'))
                    box = (x + 10, y + 10, x + w - 10, y + h - 28)
                    if box[0] < 0 or box[1] < 0 or box[2] > 1920 or box[3] > 1080 or box[2] <= box[0] or box[3] <= box[1]:
                        raise ValueError('bad face rectangle')
                    face = image.crop(box).resize((60,100))
                    mask = face.convert('L').point(lambda v: 255 if v < 120 else 0)
                    dark_mask = face.convert('L').point(lambda v: 255 if v < 100 else 0)
                    # Supporting color-change rejection for red/ordinary fives;
                    # this does not independently identify either tile.
                    pixels = list(face.getdata())
                    red_fraction = sum(r > 80 and r-g > 30 and r-b > 30
                                       for r,g,b in pixels) / len(pixels)
                    faces.append((mask, red_fraction, dark_mask))
            return tiles, faces
        bt,bf = parts(before)
        at,af = parts(after)
        if type(selected_index) is not int or not 0 <= selected_index < 14:
            return False
        old = [(t,f) for i,(t,f) in enumerate(zip(bt,bf)) if i != selected_index]
        new = list(zip(at[:13], af[:13]))
        if Counter(t for t,_ in old) != Counter(t for t,_ in new):
            return False
        for tile in set(t for t,_ in old):
            a = [f for t,f in old if t == tile]
            b = [f for t,f in new if t == tile]
            if len(a) > 4:
                return False
            def matches(x,y):
                glyph = ImageStat.Stat(ImageChops.difference(x[0],y[0])).mean[0] / 255 * 100
                dark = ImageStat.Stat(ImageChops.difference(x[2],y[2])).mean[0] / 255 * 100
                # Seven pin's red ink can cross the 120 grayscale boundary
                # under lighting changes; preserve the same spatial limit on
                # a second, darker rendering for this one observed tile.
                return (glyph <= limit + (0.1 if tile == '6p' else 0) or (tile == '7p' and dark <= limit)) and (tile not in {'0p','5p','0s','5s'} or abs(x[1]-y[1]) <= .20)
            if not any(all(matches(x,y) for x,y in zip(a,arrangement))
                       for arrangement in permutations(b)):
                return False
        return True
    except (KeyError, TypeError, ValueError, OSError, IndexError):
        return False
