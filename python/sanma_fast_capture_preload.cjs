'use strict';
// Loaded only by the opted-in Playwright driver. Unknown versions stay unchanged.
const Module=require('module'),fs=require('fs'),crypto=require('crypto');
const original=Module._extensions['.js'];
const target=process.env.SANMA_FAST_CAPTURE_TARGET;
const status=process.env.SANMA_FAST_CAPTURE_STATUS;
const expected='1ec312b2b870dd8699914f64bafcdf6c3b0e72f24939edb71c032ec4f4da101a';
const find='send("Page.captureScreenshot", { format, quality, clip, captureBeyondViewport: !fitsViewport })';
Module._extensions['.js']=function(module,filename){
 if(filename!==target)return original(module,filename);
 Module._extensions['.js']=original;
 let changed;
 try {
  const text=fs.readFileSync(filename,'utf8');
  if(crypto.createHash('sha256').update(text).digest('hex')!==expected || text.split(find).length!==2)return original(module,filename);
  changed=text.replace(find,'send("Page.captureScreenshot", { format, quality, clip, captureBeyondViewport: !fitsViewport, optimizeForSpeed: true })');
  fs.writeFileSync(status,'patched\n',{flag:'wx',mode:0o600});
 } catch(error) {
  return original(module,filename);
 }
 // Compilation failure stops the driver; never execute a partially loaded module twice.
 return module._compile(changed,filename);
};
