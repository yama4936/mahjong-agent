"""Small 37-output CNN experiment, split by source frame; never Auto-certifies.

Uses the normalized crop manifest emitted by benchmark-live-recognition.ts.
Missing classes are explicitly reported, not synthesized or claimed learned.
"""
import json
import hashlib
import random
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageEnhance
from torch import nn

random.seed(20260920)
torch.manual_seed(20260920)
torch.set_num_threads(4)
root = Path("artifacts/recognition-ablation")
directory = root / "normalized-live"
manifest = json.loads((directory / "manifest.json").read_text())
classes = [f"{n}{s}" for s in "mps" for n in range(1,10)] + list("ESWNPFC") + ["0m","0p","0s"]
groups = sorted({r["sourceScreenshot"] for r in manifest if r.get("sourceScreenshot")})
held_groups = set(groups[-2:])
held = [r for r in manifest if r.get("sourceScreenshot") in held_groups]
digest = lambda r: hashlib.sha256((directory / r["crop"]).read_bytes()).hexdigest()
held_hashes = {digest(r) for r in held}
train = [r for r in manifest if r.get("sourceScreenshot") not in held_groups and digest(r) not in held_hashes]
trained = {r["label"] for r in train}

def tensor(row, augment=False):
    image = Image.open(directory / row["crop"]).convert("RGB").resize((32,48))
    if augment:
        image = ImageEnhance.Brightness(image).enhance(random.uniform(.85,1.15))
        image = image.rotate(random.uniform(-3,3), translate=(random.randint(-1,1),random.randint(-1,1)), fillcolor=(220,220,220))
    return torch.from_numpy(np.array(image).copy()).permute(2,0,1).float()/255

model = nn.Sequential(
    nn.Conv2d(3,16,3,padding=1),nn.ReLU(),nn.MaxPool2d(2),
    nn.Conv2d(16,32,3,padding=1),nn.ReLU(),nn.MaxPool2d(2),
    nn.Flatten(),nn.Linear(32*12*8,128),nn.ReLU(),nn.Dropout(.15),nn.Linear(128,37),
)
optimizer = torch.optim.Adam(model.parameters(),lr=.001)
started = time.monotonic()
for epoch in range(100):
    model.train(); random.shuffle(train)
    for offset in range(0,len(train),24):
        batch=train[offset:offset+24]
        x=torch.stack([tensor(r,True) for r in batch])
        y=torch.tensor([classes.index(r["label"]) for r in batch])
        optimizer.zero_grad(); loss=nn.functional.cross_entropy(model(x),y); loss.backward(); optimizer.step()
    if epoch%20==0: print(json.dumps({"epoch":epoch,"loss":float(loss.detach())}),flush=True)
model.eval()
with torch.inference_mode():
    probabilities=model(torch.stack([tensor(r) for r in held])).softmax(-1)
rows=[]
for row,probs in zip(held,probabilities):
    value,index=probs.max(0); label=classes[int(index)]
    rows.append({"crop":row["crop"],"expected":row["label"],"predicted":label,"score":float(value),"accepted":float(value)>=.98 and label in trained})
accepted=[r for r in rows if r["accepted"]]
report={"classes":classes,"missingTrainingClasses":sorted(set(classes)-trained),"trainingImages":len(train),"testImages":len(rows),
    "correct":sum(r["expected"]==r["predicted"] for r in rows),"accepted":len(accepted),"acceptedErrors":sum(r["expected"]!=r["predicted"] for r in accepted),
    "trainingSeconds":time.monotonic()-started,"heldSourceFrames":sorted(held_groups),"rows":rows,
    "limitations":["Same-session source-frame split, not separate matches.","37 outputs does not mean 37 learned classes; see missingTrainingClasses.","Softmax is not calibrated probability. Experimental only; no automatic clicks."]}
(root/"cnn37-report.json").write_text(json.dumps(report,indent=2))
torch.save({"model":model.state_dict(),"classes":classes,"trainedClasses":sorted(trained)},root/"cnn37-experiment.pt")
print(json.dumps({k:v for k,v in report.items() if k!="rows"}),flush=True)
