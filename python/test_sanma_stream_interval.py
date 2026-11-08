import os,time,unittest
from sanma_stream_interval import DeliveryInterval

class IntervalTests(unittest.TestCase):
 def test_nominal_is_only_candidate(self):
  s=DeliveryInterval();[s.add(t,t) for t in (1,1.2,1.4)];r=s.result(1.5)
  self.assertEqual(r['status'],'bounded_delivery_candidate');self.assertFalse(r['confirmed']);self.assertFalse(r['operationAuthorized'])
 def test_missing_gap_reorder_detach_and_old(self):
  for series in (((1,1),(1.2,1.2),(2.2,2.2)),((1,1),(1.2,1.2),(1.1,1.3)),((1,1),(1.2,1.2),(1.3,1.1))):
   with self.subTest(series=series):
    s=DeliveryInterval();[s.add(*x) for x in series];self.assertEqual(s.result(2.3)['status'],'rejected')
  s=DeliveryInterval();[s.add(t,t) for t in (1,1.2,1.4)];self.assertEqual(s.result(3)['status'],'rejected');s.detach();self.assertEqual(s.result(1.5)['status'],'rejected')
 def test_invalid_nonfinite(self):
  for value in (float('nan'),None,True):
   s=DeliveryInterval();s.add(value,1);self.assertEqual(s.result(1)['status'],'rejected')

class IsolatedChromiumTests(unittest.TestCase):
 @unittest.skipUnless(os.environ.get("SANMA_TEST_CHROMIUM"),"isolated Chromium executable not configured")
 def test_isolated_screencast_delivery_and_disconnect(self):
  from playwright.sync_api import sync_playwright
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ['SANMA_TEST_CHROMIUM'],headless=True,args=['--no-sandbox','--disable-background-networking'])
   try:
    page=browser.new_page(viewport={'width':640,'height':360})
    page.set_content('<canvas id="c" width="640" height="360"></canvas><script>let n=0,c=document.getElementById("c").getContext("2d");function f(){c.fillStyle=`hsl(${n++%360} 90% 50%)`;c.fillRect(0,0,640,360);requestAnimationFrame(f)}f()</script>')
    session=page.context.new_cdp_session(page);tracker=DeliveryInterval(max_gap=1.5)
    def receive(event):
     tracker.add(event['metadata']['timestamp'],time.monotonic())
     session.send('Page.screencastFrameAck',{'sessionId':event['sessionId']})
    session.on('Page.screencastFrame',receive);session.send('Page.startScreencast',{'format':'png','everyNthFrame':1})
    until=time.monotonic()+8
    while tracker.count<5 and time.monotonic()<until:page.wait_for_timeout(50)
    self.assertGreaterEqual(tracker.count,5)
    self.assertEqual(tracker.result(time.monotonic(),max_age=1.5)['status'],'bounded_delivery_candidate')
    session.send('Page.stopScreencast');session.detach();tracker.detach()
    self.assertEqual(tracker.result(time.monotonic())['status'],'rejected')
   finally:browser.close()
