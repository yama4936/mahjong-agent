"""Single, unconfirmed pass of an observed pon-only CPU friend prompt."""
import hashlib
import math
import time
import uuid
from pathlib import Path

from sanma_friend_freshness import friend_action_started_at, friend_frame_stable, latch_friend_action_target
from screen_state import classify_screen, require_sanma_observable_frame


_UNSENT_PASS = object()


class PassPreclickChanged(RuntimeError):
    """The frame was rejected before any skip input was attempted."""
    def __init__(self, message, token=None):
        super().__init__(message)
        self._token = token


def pass_was_not_sent(error):
    return isinstance(error, PassPreclickChanged) and error._token is _UNSENT_PASS


def may_reobserve_unsent_pass(error, failures, watch, active, started, now):
    try:
        return (pass_was_not_sent(error) and type(failures) is int and 0 < failures < 30
                and active is True and watch.alive() is True
                and type(started) in (int, float) and math.isfinite(started)
                and type(now) in (int, float) and math.isfinite(now) and 0 <= now-started < 300)
    except Exception:
        return False


def execute_friend_pon_pass(operator, page, receipt, *, declare_riichi=False, pon_monitor=None):
    args = operator.args
    if (getattr(args, 'rules', None) != 'sanma' or getattr(args, 'mode', None) != 'force-auto'
            or getattr(args, 'action_deadline_ms', None) != 300000
            or getattr(args, 'ranked_loop', None) is not False
            or getattr(args, 'experimental_sanma_friend', None) is not True
            or getattr(operator, 'verified_friend_300_active', None) is not True):
        raise RuntimeError('verified experimental CPU friend session required')
    started = friend_action_started_at(operator)
    if type(started) not in (int, float) or not math.isfinite(started) or not 0 <= time.monotonic() - started < 300:
        raise RuntimeError('friend session timing unknown or expired')
    source = receipt.get('sourceObservation') or {}
    report = source.get('report') or {}
    row = report.get('buttonRow') or {}
    slots = (row.get('value') or {}).get('slots')
    freshness = receipt.get('freshness') or {}
    monitored = (pon_monitor is not None and getattr(args, 'experimental_sanma_pon_monitor', False) is True
                 and not declare_riichi)
    if (receipt.get('scope') != 'sanma_self_turn_observation' or receipt.get('status') != 'blocked'
            or receipt.get('operationAuthorized') is not False or source.get('operationAuthorized') is not False
            or source.get('digest') != receipt.get('digest') or report.get('digest') != receipt.get('digest')
            or (freshness.get('status') not in ('identical_pixels_candidate','stable_except_clock_candidate','stable_pon_pass_candidate')
                and not (monitored and freshness.get('status') == 'changed'))
            or freshness.get('operationAuthorized') is not False
            or type(freshness.get('elapsedMs')) not in (int,float) or not 0 <= freshness['elapsedMs'] <= 20000
            or row.get('status') != 'candidate' or (row.get('value') or {}).get('ronReferenceCompared') is not True
            or not isinstance(slots,list) or len(slots) != 3):
        raise RuntimeError('observation is incomplete or stale')
    if any(not isinstance(slot,dict) or slot.get('slot') != i for i,slot in enumerate(slots)):
        raise RuntimeError('action slots unknown')
    first, second, skip = slots
    permitted = (first.get('status') == 'empty_candidate' and second.get('action') in ('pon','kan','riichi')) or (
        first.get('status') == 'candidate' and first.get('action') == 'pon'
        and type(first.get('confidence')) in (float,int) and .98 <= first['confidence'] <= 1
        and second.get('action') == 'kan')
    if (not permitted or second.get('status') != 'candidate'
            or skip.get('status') != 'candidate' or skip.get('action') != 'skip'
            or any(type(slots[i].get('confidence')) not in (float,int) or not .99 <= slots[i]['confidence'] <= 1 for i in (1,2))):
        raise RuntimeError('optional prompt is unknown or ambiguous')
    options = [slot['action'] for slot in slots[:2] if slot.get('status') == 'candidate']
    candidates = (receipt.get('candidates') or {}).get('candidates')
    if not isinstance(candidates,list) or sorted(item.get('action') for item in candidates if isinstance(item,dict)) != sorted(options):
        raise RuntimeError('recognized options differ from candidate actions')
    if declare_riichi and options != ['riichi']:
        raise RuntimeError('riichi declaration requires a unique riichi prompt')
    baseline = Path(receipt['screenshot']).read_bytes()
    if hashlib.sha256(baseline).hexdigest() != receipt.get('digest'):
        raise RuntimeError('baseline changed')
    fresh = page.screenshot(animations='disabled')
    require_sanma_observable_frame(fresh)
    diagnostic = {'stage': 'strict_frame'}
    if monitored and freshness.get('status') == 'changed':
        # All stream frames and the baseline/fresh capture are checked.
        # No source-level frame counter exists; an omitted intermediate frame
        # remains a documented limitation of this experimental friend path.
        stable = pon_monitor.matches(report, baseline, fresh)
        diagnostic = {'stage':'resident_pon_monitor'}
    elif freshness.get('status') == 'stable_pon_pass_candidate':
        from sanma_friend_pon_stability import pon_pass_stability
        diagnostic = {}
        stable = pon_pass_stability(baseline, fresh, report, diagnostic=diagnostic)
    else:
        stable = friend_frame_stable(baseline, fresh)
    if not stable:
        # Only this pre-input path may be retried; evidence or logging errors
        # remain ordinary failures and can never trigger the retry path.
        path = operator.frames / f'{uuid.uuid4().hex}.sanma-pass-preclick-rejected.png'
        try:
            path.write_bytes(fresh)
            operator.log('sanma_friend_pass_preclick_rejected', screenshot=str(path),
                         digest=hashlib.sha256(fresh).hexdigest(), baselineScreenshot=receipt['screenshot'],
                         baselineDigest=receipt['digest'], diagnostic=diagnostic, confirmed=False)
        except Exception as error:
            raise RuntimeError(f'pass rejection evidence unavailable: {error}') from error
        raise PassPreclickChanged('screen changed outside clock area', _UNSENT_PASS)
    state, confidence = classify_screen(fresh, operator.screen_references)
    if state != 'match' or confidence < .95:
        raise RuntimeError('game screen not recognized')
    if operator.verified_friend_300_active is not True or not 0 <= time.monotonic() - started < 300:
        raise RuntimeError('friend session or timing expired')
    from sanma_friend_discard_experiment import require_friend_observation_budget
    require_friend_observation_budget(operator, receipt)
    latch_friend_action_target(operator,baseline,'pass')
    action = 'riichi_declaration' if declare_riichi else 'pass_optional'
    point = {'x':1010,'y':830} if declare_riichi else {'x':1300,'y':830}
    operator.log('sanma_friend_candidate_click', action=action, options=options, screenshot=receipt['screenshot'],
                 digest=receipt['digest'], clickPoint=point, confirmed=False)
    # Logging or target latching may block long enough to invalidate the
    # authorization checked above. Keep the latch if that happens so an
    # uncertain attempt can never be silently repeated.
    if operator.verified_friend_300_active is not True or not 0 <= time.monotonic() - started < 300:
        raise RuntimeError('friend session or timing expired before click')
    from sanma_friend_freshness import check_friend_recovery_guard
    check_friend_recovery_guard(operator)
    if monitored and not pon_monitor.matches(report, baseline, fresh):
        raise RuntimeError('pon monitor changed before click')
    require_friend_observation_budget(operator, receipt)
    page.mouse.click(point['x'],point['y'])
    return {'clicked':True,'action':action,'confirmation':'unknown','stopped':True}
