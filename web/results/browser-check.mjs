// Browser QA without a preview server or changes to the game browser.
import {chromium} from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const dir=new URL('./dist/',import.meta.url).pathname;
const browser=await chromium.launch({headless:true});
try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let reads=0;
 await page.route('https://jantama-live.yama.asia/results/**',async route=>{
  const name=new URL(route.request().url()).pathname.replace('/results/','');
  if(name==='data.json')reads++;
  await route.fulfill({path:path.join(dir,name),headers:{'access-control-allow-origin':'*'}});
 });
 await page.route('https://preview.test/**',async route=>{
  const name=new URL(route.request().url()).pathname.slice(1)||'index.html';
  const file=path.join(dir,name);
  if(!fs.existsSync(file))return route.fulfill({status:404,body:'not found'});
  const type=name.endsWith('.mjs')?'text/javascript':undefined;
  await route.fulfill({path:file,...(type?{contentType:type}:{})});
 });
 await page.clock.install();
 await page.goto('https://preview.test/sanma.html');
 await page.locator('#list .row').first().waitFor();
 assert.equal(await page.locator('#list .row').count(),1);
 assert.match(await page.locator('#list').innerText(),/手動支援/);
 assert.equal(await page.locator('#rank option[value="4"]').count(),0);
 assert.match(await page.locator('#stats').innerText(),/自動対局数\s+0/);
 await page.locator('#list .row').click();
 assert.equal(await page.locator('#detail').evaluate(e=>e.open),true);
 assert.match(await page.locator('#detailBody').innerText(),/41,500 点/);
 assert.match(await page.locator('#detailBody').innerText(),/手動支援/);
 await page.locator('#detailBody img').first().evaluate(img=>img.decode());
 const before=reads;await page.clock.runFor(31000);
 await page.waitForFunction(()=>document.querySelector('#refresh-status').textContent.includes('30秒'));
 assert(reads>before,'30-second polling');
 await page.locator('#close').click();
 await page.locator('[data-mode="ranked"]').click();
 assert.match(await page.locator('#list').innerText(),/記録はありません/);
 await page.setViewportSize({width:390,height:844});
 await page.locator('[data-mode="friend"]').click();
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile overflow');
 await page.goto('https://preview.test/index.html');
 await page.locator('#list .row').first().waitFor();
 assert.doesNotMatch(await page.locator('#list').innerText(),/sanma|手動支援/);
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({browser:'passed',sanmaRows:1,manualExcluded:true,polling:true,mobile:true}));
}finally{await browser.close();}
