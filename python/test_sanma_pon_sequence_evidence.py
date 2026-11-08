import io,json,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from sanma_pon_sequence_evidence import compare_sequence

class SequenceTest(unittest.TestCase):
 def setUp(self):
  frame=Image.new('RGB',(1920,1080),(20,30,60))
  with Image.open(Path(__file__).parent/'fixtures'/'sanma-pon-skip-156-row.png') as row:frame.paste(row.convert('RGB'),(600,785))
  ImageDraw.Draw(frame).rectangle((700,280,720,300),fill=(10,250,10))
  out=io.BytesIO();frame.save(out,format='PNG');self.frame=out.getvalue()
  self.report={'buttonRow':{'status':'candidate','value':{'ronReferenceCompared':True,'slots':[{'slot':0,'status':'empty_candidate','confidence':1},{'slot':1,'status':'candidate','action':'pon','confidence':1},{'slot':2,'status':'candidate','action':'skip','confidence':1}]}}}
 def samples(self):return [{'frame':self.frame,'sequence':i,'capturedAt':float(i)} for i in range(3)]
 def test_observation_does_not_authorize(self):
  r=compare_sequence(self.samples(),self.report);self.assertEqual(r['status'],'candidate');self.assertFalse(r['operationAuthorized']);self.assertFalse(r['confirmed'])
 def test_reordered_stale_missing_and_unverified_ron(self):
  for values in ([0,0,2],[0,2,1],[0,1,21]):
   s=self.samples()
   for i,v in enumerate(values):s[i]['capturedAt']=v
   self.assertEqual(compare_sequence(s,self.report)['status'],'rejected')
  s=self.samples();s[1]['sequence']=s[0]['sequence'];self.assertEqual(compare_sequence(s,self.report)['status'],'rejected')
  self.report['buttonRow']['value']['ronReferenceCompared']=False;self.assertEqual(compare_sequence(self.samples(),self.report)['status'],'rejected')
 def test_ron_or_intermediate_disappearance_reappearance_rejected(self):
  # Identical first/last prompts do not conceal a visible intermediate change.
  for box in ((600,785,800,875),(900,785,1100,875)):
   with self.subTest(box=box):
    image=Image.open(io.BytesIO(self.frame)).convert('RGB');ImageDraw.Draw(image).rectangle(box,fill='white');out=io.BytesIO();image.save(out,format='PNG')
    samples=self.samples();samples[1]['frame']=out.getvalue()
    self.assertEqual(compare_sequence(samples,self.report)['status'],'rejected')
 def test_changed_hand_offer_round_and_action(self):
  for box in ((300,950,335,995),(715,295,745,325),(910,400,950,430),(950,800,990,845),(768,544,830,614),(40,45,100,120),(680,370,740,430),(850,240,910,300)):
   with self.subTest(box=box):
    image=Image.open(io.BytesIO(self.frame)).convert('RGB');ImageDraw.Draw(image).rectangle(box,fill='white');out=io.BytesIO();image.save(out,format='PNG');s=self.samples();s[2]['frame']=out.getvalue()
    self.assertEqual(compare_sequence(s,self.report)['status'],'rejected')

ROOT=Path('/home/yama1/server/data/dev-work/jantama/evidence182/retry2-artifacts')
@unittest.skipUnless(ROOT.exists(),'retained 182 evidence unavailable')
class RealSequenceTest(unittest.TestCase):
 def test_recorded_pon_despite_wall_animation(self):
  events=[e for e in map(json.loads,(ROOT/'python-operator.jsonl').read_text().splitlines()) if e.get('event')=='sanma_self_turn_observed'];r=json.loads(Path(events[0]['receiptPath']).read_text());paths=[r['screenshot'],r['freshness']['screenshot'],events[1]['screenshot']]
  samples=[{'frame':Path(p).read_bytes(),'sequence':i,'capturedAt':float(i)} for i,p in enumerate(paths)]
  self.assertEqual(compare_sequence(samples,r['sourceObservation']['report'])['status'],'candidate')
  # A white-tile-shaped change in our river followed by the original image
  # must not be hidden by identical first and last frames.
  image=Image.open(paths[1]).convert('RGB');ImageDraw.Draw(image).rectangle((768,544,829,613),fill='white');out=io.BytesIO();image.save(out,format='PNG')
  altered=[dict(x) for x in samples];altered[1]['frame']=out.getvalue()
  self.assertEqual(compare_sequence(altered,r['sourceObservation']['report'])['status'],'rejected')
