"""Single, unconfirmed pass of an observed pon-only CPU friend prompt."""
import hashlib
import math
import time
from pathlib import Path

from sanma_friend_freshness import friend_action_started_at, friend_frame_stable, latch_friend_action_target
from screen_state import classify_screen


def execute_friend_pon_pass(operator, page, receipt):
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
    if (receipt.get('scope') != 'sanma_self_turn_observation' or receipt.get('status') != 'blocked'
            or receipt.get('operationAuthorized') is not False or source.get('operationAuthorized') is not False
            or source.get('digest') != receipt.get('digest') or report.get('digest') != receipt.get('digest')
            or freshness.get('status') not in ('identical_pixels_candidate','stable_except_clock_candidate')
            or freshness.get('operationAuthorized') is not False
            or type(freshness.get('elapsedMs')) not in (int,float) or not 0 <= freshness['elapsedMs'] <= 20000
            or row.get('status') != 'candidate' or not isinstance(slots,list) or len(slots) != 3):
        raise RuntimeError('observation is incomplete or stale')
    if (any(not isinstance(slot,dict) or slot.get('slot') != i for i,slot in enumerate(slots))
            or slots[0].get('status') != 'empty_candidate'
            or slots[1].get('status') != 'candidate' or slots[1].get('action') != 'pon'
            or slots[2].get('status') != 'candidate' or slots[2].get('action') != 'skip'
            or any(type(slots[i].get('confidence')) not in (float,int) or not .99 <= slots[i]['confidence'] <= 1 for i in (1,2))):
        raise RuntimeError('pon-only prompt is unknown or ambiguous')
    baseline = Path(receipt['screenshot']).read_bytes()
    if hashlib.sha256(baseline).hexdigest() != receipt.get('digest'):
        raise RuntimeError('baseline changed')
    fresh = page.screenshot(animations='disabled')
    if not friend_frame_stable(baseline, fresh):
        raise RuntimeError('screen changed outside clock area')
    state, confidence = classify_screen(fresh, operator.screen_references)
    if state != 'match' or confidence < .95:
        raise RuntimeError('game screen not recognized')
    if operator.verified_friend_300_active is not True or not 0 <= time.monotonic() - started < 300:
        raise RuntimeError('friend session or timing expired')
    latch_friend_action_target(operator,baseline,'pass')
    operator.log('sanma_friend_candidate_click', action='pass_pon', screenshot=receipt['screenshot'],
                 digest=receipt['digest'], clickPoint={'x':1300,'y':830}, confirmed=False)
    page.mouse.click(1300,830)
    return {'clicked':True,'action':'pass_pon','confirmation':'unknown','stopped':True}
