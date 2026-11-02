"""Temporary, version-pinned PNG compression hook for one Playwright driver."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import inspect
import uuid

EXPECTED_SHA256='1ec312b2b870dd8699914f64bafcdf6c3b0e72f24939edb71c032ec4f4da101a'
EXPECTED_VERSION='1.55.0'

@contextmanager
def fast_capture_driver_environment(enabled, status_directory):
    """Modify only the environment passed to the next Playwright driver spawn.

    Validation failures leave the stock screenshot implementation in place.
    A status marker is advisory evidence, not a screenshot freshness proof.
    """
    state={'requested':bool(enabled),'status':'disabled','marker':None}
    if not enabled:
        yield state
        return
    try:
        import playwright
        import playwright._repo_version as version
        import playwright._impl._transport as transport
        root=Path(inspect.getfile(playwright)).parent
        target=root/'driver/package/lib/server/chromium/crPage.js'
        preload=Path(__file__).with_name('sanma_fast_capture_preload.cjs').resolve()
        if (version.version != EXPECTED_VERSION or not preload.is_file()
                or any(c.isspace() or c in '\"\'' for c in str(preload))
                or sha256(target.read_bytes()).hexdigest()!=EXPECTED_SHA256):
            state['status']='fallback_incompatible_driver'
        else:
            marker=Path(status_directory)/('fast-png-driver-'+uuid.uuid4().hex+'.status')
            original=transport.get_driver_env
            def driver_env():
                env=original()
                env['NODE_OPTIONS']=(env.get('NODE_OPTIONS','')+' --require='+str(preload)).strip()
                env['SANMA_FAST_CAPTURE_TARGET']=str(target)
                env['SANMA_FAST_CAPTURE_STATUS']=str(marker)
                return env
            state.update(status='pending',marker=str(marker))
    except (OSError, ImportError, AttributeError):
        state['status']='fallback_setup_error'
    if state['status'] != 'pending':
        yield state
        return
    transport.get_driver_env=driver_env
    try:yield state
    finally:transport.get_driver_env=original
