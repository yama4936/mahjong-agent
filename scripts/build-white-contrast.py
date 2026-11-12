from pathlib import Path
from PIL import Image, ImageDraw
import hashlib,json,sys
if len(sys.argv) != 3:
 raise SystemExit('Usage: python scripts/build-white-contrast.py SOURCE_054 OUTPUT_DIRECTORY')
out=Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
repo=Path(__file__).resolve().parent.parent/'test/fixtures'
e189=Path(sys.argv[1])
if hashlib.sha256(e189.read_bytes()).hexdigest() != '7f5f0c281c1a692cbdfe41c9613adaa914c5d809b739c7abe1227d35e529de4a':
 raise SystemExit('Unexpected source image; labels and coordinates are not verified')
cases=[('sanma_white1',e189,(1266,921,1359,1072),'white','same frame as sanma_white2 and sanma_south'),('sanma_white2',e189,(1361,921,1453,1072),'white','same frame as sanma_white1 and sanma_south'),('sanma_south',e189,(1171,921,1264,1072),'south','same frame as sanma_white1'),('yonma_white_draw',repo/'selection-white-draw-timer-before-20261028.png',(1485,921,1578,1072),'white','same scene as selection-white-draw-timer-lift-20261028.png'),('yonma_white_raised',repo/'selection-white-lift-20261028.jpg',(1360,873,1454,1025),'white with petals','different scene from yonma_white_draw and selection-white-riichi-timer-lift-20261028.png'),('yonma_south',repo/'hand-nine-sou-before-glare-20261021.jpg',(1485,921,1578,1072),'south','four-player ranked'),('table',e189,(1266,700,1359,851),'table background','same frame as sanma_white1')]
manifest=[]
for name,path,box,label,rel in cases:
 im=Image.open(path).convert('RGB').crop(box); target=out/(name+'.png'); im.save(target)
 manifest.append(dict(name=name,source=str(path),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),crop=list(box),label=label,relationship=rel,output=str(target),output_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
# Deliberate adversarial image: retain a real non-white tile rim and replace its glyph region.
im=Image.open(out/'sanma_south.png').convert('RGB'); draw=ImageDraw.Draw(im); draw.rectangle((8,20,84,115),fill=im.getpixel((10,20))); target=out/'synthetic_south_white_occlusion.png'; im.save(target)
manifest.append(dict(name='synthetic_south_white_occlusion',source=str(out/'sanma_south.png'),label='synthetic south; glyph covered by opaque constant-color rectangle',relationship='derived from same sanma_south crop, not an independent real-world example',output=str(target),output_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
# A second synthetic counterexample copies a real white face over the South glyph,
# retaining the South tile's outer edges. This simulates, but does not establish,
# an opaque face-colored overlay or unloaded glyph in an actual game.
south=Image.open(out/'sanma_south.png').convert('RGB')
white=Image.open(out/'sanma_white1.png').convert('RGB')
south.paste(white.crop((5,20,87,140)), (5,20))
target=out/'synthetic_south_white_face.png'; south.save(target)
manifest.append(dict(name='synthetic_south_white_face',source=str(out/'sanma_south.png'),label='synthetic south; glyph covered with real white tile face',relationship='derived from sanma_south and sanma_white1, not an independent real-world example',output=str(target),output_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(manifest,ensure_ascii=False,indent=2))
