"""Narrow unverified ordinary five-pin face hypothesis for friend recovery."""
import io
from PIL import Image


def ordinary_five_pin_face_candidate(frame, slot):
    try:
        x,y,w,h=(slot[k] for k in ('x','y','width','height'))
        if any(type(v) is not int for v in (x,y,w,h)) or not (0<=x and 0<=y and 70<=w<=110 and 120<=h<=180 and x+w<=1920 and y+h<=1080):
            return False
        with Image.open(io.BytesIO(frame)) as source:
            if source.size!=(1920,1080):return False
            image=source.convert('RGB').crop((x,y,x+w,y+h)).resize((93,151))
        def counts(box):
            pixels=list(image.crop(box).getdata())
            black=sum(max(p)<100 for p in pixels)
            red=sum(r>g*1.4 and r>b*1.3 and r>55 for r,g,b in pixels)
            return black,red
        quadrants=[counts(box) for box in ((5,20,43,65),(50,20,88,65),(5,85,43,130),(50,85,88,130))]
        core=counts((30,50,63,105))
        return all(black>=300 and red<=150 for black,red in quadrants) and core[1]>=250
    except (KeyError,TypeError,ValueError,IndexError,OSError):
        return False
