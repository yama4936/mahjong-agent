"""Opt-in diagnostics: records screenshots, never certifies game state."""
import fcntl, hashlib, json, os, queue, stat, threading, time
from pathlib import Path

class Session:
 MAX_FRAME=4*1024*1024; MAX_TOTAL=32*1024*1024; MAX_COUNT=20; MAX_PARENT=256*1024*1024; MAX_SECONDS=30
 def __init__(self,parent,name,*,opt_in,verified_friend,ranked,deadline_ms,clock,commit):
  if not (opt_in is True and verified_friend is True and ranked is False and deadline_ms == 300000 and clock == '300+0'):
   raise ValueError('explicit opt-in and verified 300+0 friend required')
  if not isinstance(commit,str) or len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit): raise ValueError('commit')
  if not name or Path(name).name!=name or name in ('.','..'): raise ValueError('name')
  root=Path(parent).absolute()
  # Require a private directory; ownership is the trust boundary for all paths.
  st=os.lstat(root)
  if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode & 0o077:
   raise ValueError('recording root must be private and owned by current user')
  # Lock the parent directory inode, not a removable file or the root inode.
  # All cooperating recorders under this parent serialize quota reservations.
  parent_fd=os.open(root.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
  self.lock=parent_fd
  try:
   fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   opened_parent=os.fstat(self.lock)
   current_parent=os.stat(root.parent,follow_symlinks=False)
   if (opened_parent.st_dev,opened_parent.st_ino)!=(current_parent.st_dev,current_parent.st_ino): raise ValueError('parent replaced')
   current=os.lstat(root)
   if (current.st_dev,current.st_ino)!=(st.st_dev,st.st_ino): raise ValueError('root replaced')
   self.root=root; self.root_identity=(st.st_dev,st.st_ino)
   used=0
   for base,dirs,files in os.walk(root,followlinks=False):
    for n in dirs+files:
     p=Path(base)/n
     if p.is_symlink(): raise ValueError('symlink')
     if p.is_file(): used+=p.stat().st_size
   if used+self.MAX_TOTAL+65536>self.MAX_PARENT: raise ValueError('quota')
   self.path=root/name; self.path.mkdir(mode=0o700)
   self._atomic('started.json',dict(version=1,confirmed=False,commit=commit,clock=clock,deadlineMs=deadline_ms))
  except BaseException:
   os.close(self.lock); raise
  self.q=queue.Queue(maxsize=2); self.mu=threading.Lock(); self.closed=False; self.failed=False
  self.accepted=0; self.dropped=0; self.total=0; self.results=[]; self.error=None; self.serial=0
  self.worker=threading.Thread(target=self._run,daemon=True); self.worker.start()
 def _atomic(self,name,value):
  p=self.path/(name+'.partial')
  with p.open('xb') as f: f.write(json.dumps(value,separators=(',',':')).encode())
  os.replace(p,self.path/name)
 def begin(self,action,verified_friend):
  if action not in ('kita','discard','pass_pon','riichi','ron','tsumo') or verified_friend is not True: raise ValueError('transition')
  with self.mu:
   if self.closed or self.failed: raise RuntimeError('closed')
   self.serial+=1; return Transition(self,self.serial,action,time.monotonic_ns())
 def _offer(self,t,data,start,end):
  with self.mu:
   if self.closed: return False
   if (self.failed or t.closed or not isinstance(data,bytes) or not data or len(data)>self.MAX_FRAME or
       self.accepted>=self.MAX_COUNT or self.total+len(data)>self.MAX_TOTAL or
       not isinstance(start,int) or not isinstance(end,int) or start<t.start or end<start or
       end>t.start+self.MAX_SECONDS*1000000000):
    self.dropped+=1; return False
   item=(self.accepted,t.serial,t.action,data,start,end)
   try: self.q.put_nowait(item)
   except queue.Full: self.dropped+=1; return False
   self.accepted+=1; self.total+=len(data); return True
 def _run(self):
  try:
   while True:
    try: item=self.q.get(timeout=.05)
    except queue.Empty:
     with self.mu:
      if self.closed: break
     continue
    current=os.lstat(self.root)
    if (current.st_dev,current.st_ino)!=self.root_identity: raise ValueError('recording root replaced')
    i,serial,action,data,start,end=item; name=f'{i:02}.png'; temp=self.path/(name+'.partial')
    with temp.open('xb') as f: f.write(data)
    os.replace(temp,self.path/name)
    self.results.append(dict(index=i,transition=serial,action=action,image=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),captureStartNs=start,captureEndNs=end,confirmed=False))
  except Exception as e:
   with self.mu: self.failed=True; self.error=f'{type(e).__name__}: {e}'
   while True:
    with self.mu:
     if self.closed: break
    time.sleep(.01)
  finally:
   try:
    written={x['index'] for x in self.results}
    self._atomic('final.json',dict(version=1,confirmed=False,timingMeaning='screenshot call interval, not render time',accepted=self.accepted,dropped=self.dropped,written=len(self.results),missingAccepted=[i for i in range(self.accepted) if i not in written],error=self.error,frames=self.results))
   except Exception: self.failed=True
   os.close(self.lock)
 def close(self):
  with self.mu: self.closed=True

class Transition:
 def __init__(self,session,serial,action,start): self.session=session; self.serial=serial; self.action=action; self.start=start; self.closed=False
 def close(self):
  with self.session.mu: self.closed=True
 def screenshot(self,page,*args,**kwargs):
  start=time.monotonic_ns(); image=page.screenshot(*args,**kwargs); end=time.monotonic_ns()
  try: self.session._offer(self,image,start,end)
  except Exception: pass
  return image

class PageProxy:
 def __init__(self,page,transition): self.page=page; self.transition=transition
 def __getattr__(self,name): return getattr(self.page,name)
 def screenshot(self,*args,**kwargs): return self.transition.screenshot(self.page,*args,**kwargs)
