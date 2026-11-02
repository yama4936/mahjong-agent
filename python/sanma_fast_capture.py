"""Version-pinned PNG hook with a per-instance Playwright transport.

The scoped context and transport mirror Playwright 1.55.0's MIT-licensed
implementations. Their exact source digests are verified before this code runs.
No process environment or Playwright module global is changed.
"""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import inspect
import uuid

EXPECTED_SHA256='1ec312b2b870dd8699914f64bafcdf6c3b0e72f24939edb71c032ec4f4da101a'
EXPECTED_CONTEXT_SHA256='d40604253e11521d64029b7154e164f81e33e1d11269da6b412015d6bb4b291b'
EXPECTED_TRANSPORT_SHA256='896dda8a25b612f46119fa25bcaed0f026ee719a85bd7b47972612ae47b6d00f'
EXPECTED_VERSION='1.55.0'

class ScopedStartupCleanupError(RuntimeError):
    """A failed driver could not be proven stopped; do not start another."""

def scoped_playwright_factory(driver_options):
    """Create a one-use sync manager whose child alone receives driver_options."""
    import asyncio
    import subprocess
    import sys
    from greenlet import greenlet
    from playwright._impl._connection import Connection
    from playwright._impl._errors import Error
    from playwright._impl._greenlets import MainGreenlet
    from playwright._impl._object_factory import create_remote_object
    from playwright._impl._transport import PipeTransport, _get_stderr_fileno
    import playwright._impl._transport as transport_module
    from playwright._impl._driver import compute_driver_executable, get_driver_env
    from playwright.sync_api._context_manager import PlaywrightContextManager
    from playwright.sync_api._generated import Playwright as SyncPlaywright

    class ScopedTransport(PipeTransport):
        async def connect(self):
            self._stopped_future=self._loop.create_future()
            try:
                env=get_driver_env()
                if getattr(sys,'frozen',False) or vars(transport_module).get('__compiled__'):
                    env.setdefault('PLAYWRIGHT_BROWSERS_PATH','0')
                env.update(driver_options)
                startupinfo=None
                if sys.platform=='win32':
                    startupinfo=subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow=subprocess.SW_HIDE
                executable,entrypoint=compute_driver_executable()
                self._proc=await asyncio.create_subprocess_exec(executable,entrypoint,'run-driver',
                    stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,
                    stderr=_get_stderr_fileno(),limit=32768,env=env,startupinfo=startupinfo)
            except Exception as error:
                self.on_error_future.set_exception(error)
                raise
            self._output=self._proc.stdin

    class ScopedContext(PlaywrightContextManager):
        def __init__(self):
            super().__init__();self._entered=False
        def __enter__(self):
            if self._entered:raise RuntimeError('scoped Playwright manager cannot be reentered')
            self._entered=True
            try:self._loop=asyncio.get_running_loop()
            except RuntimeError:
                self._loop=asyncio.new_event_loop();self._own_loop=True
            if self._loop.is_running():
                raise Error('Playwright Sync API cannot run inside an asyncio loop')
            def dispatch():self._loop.run_until_complete(self._connection.run_as_sync())
            try:
                self._connection=Connection(MainGreenlet(dispatch),create_remote_object,ScopedTransport(self._loop),self._loop)
                caller=greenlet.getcurrent()
                def receive(owner):
                    self._playwright=SyncPlaywright(owner);caller.switch()
                self._connection.call_on_object_with_known_name('Playwright',receive)
                self._connection._dispatcher_fiber.switch()
                playwright=self._playwright;playwright.stop=self.__exit__
                return playwright
            except BaseException as error:
                try:
                    transport=getattr(getattr(self,'_connection',None),'_transport',None)
                    process=getattr(transport,'_proc',None)
                    if process is not None and process.returncode is None:
                        process.kill()
                        self._loop.run_until_complete(asyncio.wait_for(process.wait(),2))
                    if self._own_loop and not self._loop.is_closed():
                        tasks=asyncio.all_tasks(self._loop)
                        for task in tasks:task.cancel()
                        if tasks:self._loop.run_until_complete(asyncio.gather(*tasks,return_exceptions=True))
                        self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                        self._loop.close()
                except BaseException as cleanup_error:
                    raise ScopedStartupCleanupError('scoped driver cleanup failed') from cleanup_error
                raise error
    return ScopedContext()


@contextmanager
def fast_capture_driver_environment(enabled,status_directory):
    """Prepare a scoped factory, or yield a stock fallback without mutation."""
    state={'requested':bool(enabled),'status':'disabled','marker':None,'factory':None}
    if not enabled:
        yield state
        return
    try:
        import playwright
        import playwright._repo_version as version
        root=Path(inspect.getfile(playwright)).parent
        target=root/'driver/package/lib/server/chromium/crPage.js'
        preload=Path(__file__).with_name('sanma_fast_capture_preload.cjs').resolve()
        files=((target,EXPECTED_SHA256),(root/'sync_api/_context_manager.py',EXPECTED_CONTEXT_SHA256),
               (root/'_impl/_transport.py',EXPECTED_TRANSPORT_SHA256))
        if (version.version != EXPECTED_VERSION or not preload.is_file()
                or any(c.isspace() or c in '\"\'' for c in str(preload))
                or any(sha256(path.read_bytes()).hexdigest()!=digest for path,digest in files)):
            state['status']='fallback_incompatible_driver'
        else:
            marker=Path(status_directory)/('fast-png-driver-'+uuid.uuid4().hex+'.status')
            # get_driver_env is called by this transport, with no global patch.
            from playwright._impl._driver import get_driver_env
            env=get_driver_env()
            options={'NODE_OPTIONS':(env.get('NODE_OPTIONS','')+' --require='+str(preload)).strip(),
                     'SANMA_FAST_CAPTURE_TARGET':str(target),'SANMA_FAST_CAPTURE_STATUS':str(marker)}
            state.update(status='pending',marker=str(marker),factory=lambda:scoped_playwright_factory(options))
    except (OSError,ImportError,AttributeError):
        state['status']='fallback_setup_error'
    yield state
