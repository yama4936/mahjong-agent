"""Narrow friend-only visual comparison for one reviewed pon/skip prompt."""
import io
from pathlib import Path
from PIL import Image, ImageChops, ImageStat


def pon_pass_stability(before, after, report, *, on_wall_error=None, diagnostic=None):
    try:
        if diagnostic is not None: diagnostic.update(stage='pon_row')
        row=report['buttonRow']; value=row['value']; slots=value['slots']
        if row['status']!='candidate' or value.get('ronReferenceCompared') is not True or len(slots)!=3:
            return False
        if any(type(s.get('slot')) is not int or s['slot']!=i for i,s in enumerate(slots)): return False
        if (slots[0].get('status')!='empty_candidate' or slots[1].get('status')!='candidate'
                or slots[1].get('action')!='pon' or slots[2].get('status')!='candidate' or slots[2].get('action')!='skip'
                or any(type(s.get('confidence')) not in (int,float) or not .99<=s['confidence']<=1 for s in slots)):
            return False
        with Image.open(io.BytesIO(before)) as aa, Image.open(io.BytesIO(after)) as bb, Image.open(Path(__file__).parent/'fixtures'/'sanma-pon-skip-156-row.png') as rr:
            a,b=aa.convert('RGB'),bb.convert('RGB');ref=rr.convert('RGB').crop((0,0,824,90))
            if a.size!=(1920,1080) or b.size!=a.size or ref.size!=(824,90):return False
            for im in (a,b):
                delta=ImageChops.difference(im.crop((600,785,1424,875)),ref)
                if max(ImageStat.Stat(delta).mean)>.1:return False
                if any(max(ImageStat.Stat(delta.crop((x,y,min(x+8,824),min(y+8,90)))).mean)>10
                       for y in range(0,90,8) for x in range(0,824,8)):return False
            from auto_operator import experimental_kita_wall_color_stable, experimental_kita_color_stable
            if diagnostic is not None: diagnostic.update(stage='wall_color')
            if not experimental_kita_wall_color_stable(before,after,on_error=on_wall_error):return False
            if diagnostic is not None: diagnostic.update(stage='hand_color')
            if not experimental_kita_color_stable(before,after,[{'x':220,'y':921,'width':1235,'height':151},
                                                                 {'x':650,'y':210,'width':600,'height':420}]):return False
            if diagnostic is not None: diagnostic.update(stage='binary_frame')
            masks=[im.convert('L').point(lambda v:255 if v<120 else 0) for im in (a,b)]
            delta=ImageChops.difference(*masks);delta.paste(0,(1425,755,1650,870))
            for y in range(0,1080,32):
                for x in range(0,1920,32):
                    changed=delta.crop((x,y,min(x+32,1920),min(y+32,1080))).histogram()[255]
                    if changed>14:
                        if diagnostic is not None: diagnostic.update(blockX=x,blockY=y,changedPixels=changed)
                        return False
            return True
    except (AttributeError,KeyError,TypeError,ValueError,OSError,IndexError):return False
