"""Fail-closed skip of a visually identified nine-terminals friend prompt.

The default is to continue the hand. Recognition is limited to the reviewed
1920x1080 button appearance; an unmatched theme is never acted upon.
"""
import hashlib
import io
import math
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageStat
from screen_state import classify_screen, require_sanma_observable_frame
from sanma_friend_discard_recovery import MatchContinuity
from sanma_friend_freshness import (check_friend_recovery_guard, friend_action_started_at,
                                    latch_friend_action_target)
from sanma_friend_discard_experiment import require_friend_observation_budget

_ASSETS = Path(__file__).parent / 'assets'
_BOXES = (((930, 790, 1100, 865), 'sanma-kyuushu-friend.png'),
          ((1210, 800, 1380, 860), 'sanma-skip-friend.png'))
_ORPHANS = {'1m','9m','1p','9p','1s','9s','E','S','W','N','P','F','C'}


def prompt_matches(frame):
    try:
        if isinstance(frame, bytes):
            image = Image.open(io.BytesIO(frame)).convert('RGB')
        else:
            image = frame.convert('RGB')
        if image.size != (1920, 1080): return False
        for box, filename in _BOXES:
            with Image.open(_ASSETS / filename) as template:
                diff = ImageChops.difference(image.crop(box), template.convert('RGB'))
                if max(ImageStat.Stat(diff).mean) > 1: return False
        return True
    except (OSError, ValueError, TypeError):
        return False


def recognizable(receipt):
    try:
        source=receipt['sourceObservation']; report=source['report']
        row=report['buttonRow']; slots=row['value']['slots']; hand=report['hand']
        tiles=hand['value']['tiles']
        actions=receipt['candidates']['candidates']
        return (receipt['scope']=='sanma_self_turn_observation' and receipt['status']=='blocked'
                and receipt['operationAuthorized'] is False and source['operationAuthorized'] is False
                and receipt['digest']==source['digest']==report['digest']
                and row['status']=='candidate' and row['value']['ronReferenceCompared'] is True
                and len(slots)==3 and all(type(slot.get('slot')) is int and slot['slot']==i for i,slot in enumerate(slots))
                and slots[0]['status']=='empty_candidate'
                and slots[1]['status']=='unresolved'
                and slots[2]['status']=='candidate' and slots[2]['action']=='skip'
                and type(slots[2]['confidence']) in (int,float) and .99<=slots[2]['confidence']<=1
                and actions==[]
                and hand['status']=='candidate' and hand['value']['turnReady'] is True
                and hand['value']['candidateMelds']==0 and len(tiles)==14
                and len(set(tiles)&_ORPHANS)>=9)
    except (KeyError, TypeError, ValueError):
        return False


def recovered_empty_pair(operator, baseline, original, observed, frame, captured, watch, started):
    """Independently recognize the fresh image before continuing the same turn."""
    try:
        if (operator.verified_friend_300_active is not True or not watch.alive()
                or not 0 <= time.monotonic()-started < 300): return False
        source=observed['sourceObservation'];report=source['report'];row=report['buttonRow']['value']
        hand=report['hand']['value'];geometry=report['handGeometry']['value']
        board=source['board']['candidate'];original_board=original['sourceObservation']['board']['candidate']
        before_tiles=original['sourceObservation']['report']['hand']['value']['tiles']
        path=Path(observed['screenshot']);fresh_path=Path(observed['freshness']['screenshot'])
        data=path.read_bytes();fresh=fresh_path.read_bytes()
        from auto_operator import closed_hand_face_mismatches, experimental_draw_glyph_stability, sanma_draw_observation_candidate
        from sanma_friend_discard_experiment import friend_visible_empty_row_candidate
        keys=('seat','round','honba','scores','remainingTiles','riichiSticks')
        if not (observed['captureStartedMonotonic']==captured
                and hashlib.sha256(frame).hexdigest()==hashlib.sha256(data).hexdigest()==observed['digest']==report['digest']==source['digest']
                and hashlib.sha256(fresh).hexdigest()==observed['freshness']['digest']
                and observed['freshness']['status']=='stable_draw_glyph_candidate'
                and observed['freshness']['operationAuthorized'] is False
                and observed['scope']=='sanma_self_turn_observation' and observed['operationAuthorized'] is False
                and source['operationAuthorized'] is False and observed['candidates']['candidates']==[]
                and source['candidates']['candidates']==[]
                and len(row['slots'])==3 and all(type(slot.get('slot')) is int and slot['slot']==i for i,slot in enumerate(row['slots']))
                and report['buttonRow']['status']=='candidate' and report['hand']['status']=='candidate'
                and report['handGeometry']['status']=='candidate' and row['ronReferenceCompared'] is True
                and hand['turnReady'] is True and hand['candidateMelds']==0 and hand['tiles']==before_tiles
                and len(before_tiles)==14 and all(original_board.get(k) is not None and board.get(k)==original_board[k] for k in keys)
                and observed['drawCandidate']['status']=='candidate' and observed['drawCandidate']['digest']==observed['digest']
                and observed['drawCandidate']['index']==13 and not prompt_matches(data)
                and not closed_hand_face_mismatches(baseline,data,{'handSlots':geometry['handSlots'],'drawSlot':geometry['drawSlot']},.5)
                and friend_visible_empty_row_candidate(data,row['slots'],allow_north_overlap=False)
                and friend_visible_empty_row_candidate(fresh,row['slots'],allow_north_overlap=False)
                and experimental_draw_glyph_stability(data,fresh,report)):
            return False
        # Each image has its own read-only recognition, tied to its exact hash.
        fresh_source=operator.observe_sanma_resident(fresh_path)
        fresh_report=fresh_source['report'];fresh_row=fresh_report['buttonRow']['value']
        fresh_hand=fresh_report['hand']['value'];fresh_board=fresh_source['board']['candidate']
        fresh_draw=sanma_draw_observation_candidate(fresh_source)
        if not (fresh_source['scope']=='offline_untrusted_sanma_auto_observation'
                and fresh_source['operationAuthorized'] is False
                and fresh_source['candidates']['operationAuthorized'] is False
                and fresh_source['assembly']['operationAuthorized'] is False
                and fresh_source['assembly']['priority']['status']=='blocked'
                and fresh_source['assembly']['evaluation']['status']=='blocked'
                and hashlib.sha256(path.read_bytes()).hexdigest()==observed['digest']
                and fresh_source['digest']==fresh_report['digest']==hashlib.sha256(fresh_path.read_bytes()).hexdigest()==observed['freshness']['digest']
                and fresh_source['candidates']['candidates']==[] and fresh_report['buttonRow']['status']=='candidate'
                and fresh_report['hand']['status']=='candidate' and fresh_report['handGeometry']['status']=='candidate'
                and fresh_row['ronReferenceCompared'] is True
                and len(fresh_row['slots'])==3 and all(type(slot.get('slot')) is int and slot['slot']==i for i,slot in enumerate(fresh_row['slots']))
                and fresh_hand['turnReady'] is True
                and fresh_hand['candidateMelds']==0 and fresh_hand['tiles']==before_tiles
                and fresh_report['handGeometry']['value']==geometry
                and all(fresh_board.get(k)==original_board[k] for k in keys)
                and fresh_draw['status']=='candidate' and fresh_draw['digest']==fresh_source['digest'] and fresh_draw['index']==13
                and friend_visible_empty_row_candidate(fresh,fresh_row['slots'],allow_north_overlap=False)
                and experimental_draw_glyph_stability(data,fresh,fresh_report)):
            return False
        return (operator.verified_friend_300_active is True and watch.alive() is True
                and 0 <= time.monotonic()-started < 300)
    except (KeyError,TypeError,ValueError,OSError):
        return False


def execute(operator, page, receipt):
    """Return False if no input sent; an attempted input must not be repeated."""
    args=operator.args
    if (args.rules!='sanma' or args.mode!='force-auto' or args.action_deadline_ms!=300000
            or args.ranked_loop is not False or args.experimental_sanma_friend is not True
            or operator.verified_friend_300_active is not True or not recognizable(receipt)):
        return False
    started=friend_action_started_at(operator)
    if type(started) not in (int,float) or not math.isfinite(started) or not 0<=time.monotonic()-started<300:
        return False
    baseline=Path(receipt['screenshot']).read_bytes()
    if hashlib.sha256(baseline).hexdigest()!=receipt['digest'] or not prompt_matches(baseline): return False
    with_watch=MatchContinuity(page)
    transferred=False
    try:
        fresh=page.screenshot(animations='disabled')
        require_sanma_observable_frame(fresh)
        from auto_operator import experimental_draw_glyph_stability
        if (not with_watch.alive() or not prompt_matches(fresh)
                or not experimental_draw_glyph_stability(baseline,fresh,receipt['sourceObservation']['report'],
                                                         friend_prompt_guard=prompt_matches)):
            return False
        state, confidence=classify_screen(fresh,operator.screen_references)
        if state!='match' or confidence<.95: return False
        if operator.verified_friend_300_active is not True or not 0<=time.monotonic()-started<300:
            return False
        require_friend_observation_budget(operator,receipt)
        check_friend_recovery_guard(operator)
        if not with_watch.alive(): return False
        latch_friend_action_target(operator,baseline,'pass')
        operator.log('sanma_friend_candidate_click',action='pass_nine_terminals',policy='continue_hand',
                     screenshot=receipt['screenshot'],digest=receipt['digest'],clickPoint={'x':1300,'y':830},confirmed=False)
        # A latch is retained if anything becomes uncertain after this point.
        if (operator.verified_friend_300_active is not True or not with_watch.alive()
                or not 0<=time.monotonic()-started<300):
            raise RuntimeError('friend continuity or deadline lost before pass')
        check_friend_recovery_guard(operator)
        require_friend_observation_budget(operator,receipt)
        page.mouse.click(1300,830)
        # The unchanged hand and empty row must be observed independently
        # twice. Missing or ambiguous evidence never retries the skip.
        previous=None
        before_board=receipt['sourceObservation']['board']['candidate']
        before_tiles=receipt['sourceObservation']['report']['hand']['value']['tiles']
        for _ in range(8):
            if (operator.verified_friend_300_active is not True or not with_watch.alive()
                    or not 0<=time.monotonic()-started<300):
                raise RuntimeError('friend continuity or deadline lost after pass')
            captured=time.monotonic()
            frame=page.screenshot(animations='disabled')
            observed=operator.inspect_sanma_self_turn(page,classified_frame=frame,classified_started=captured)
            try:
                report=observed['sourceObservation']['report']
                row=report['buttonRow']['value']
                board=observed['sourceObservation']['board']['candidate']
                hand=report['hand']['value']
                geometry=report['handGeometry']['value']
                from auto_operator import closed_hand_face_mismatches
                from sanma_friend_freshness import friend_frame_stable
                data=Path(observed['screenshot']).read_bytes()
                fresh_data=Path(observed['freshness']['screenshot']).read_bytes()
                board_keys=('seat','round','honba','scores','remainingTiles','riichiSticks')
                good=(observed['captureStartedMonotonic']==captured
                    and hashlib.sha256(frame).hexdigest()==hashlib.sha256(data).hexdigest()==observed['digest']==report['digest']
                    and hashlib.sha256(fresh_data).hexdigest()==observed['freshness']['digest']
                    and observed['sourceObservation']['digest']==observed['digest']
                    and observed['scope']=='sanma_self_turn_observation' and observed['operationAuthorized'] is False
                    and observed['sourceObservation']['operationAuthorized'] is False
                    and report['buttonRow']['status']=='candidate' and report['hand']['status']=='candidate'
                    and report['handGeometry']['status']=='candidate'
                    and observed['candidates']['candidates']==[] and row['ronReferenceCompared'] is True
                    and len(row['slots'])==3
                    and all(slot.get('status')=='empty_candidate' and type(slot.get('slot')) is int and slot['slot']==i
                            for i,slot in enumerate(row['slots']))
                    and hand['tiles']==before_tiles and hand['turnReady'] is True
                    and hand['candidateMelds']==0 and len(before_tiles)==14
                    and all(before_board.get(k) is not None and board.get(k)==before_board[k] for k in board_keys)
                    and observed['drawCandidate']['status']=='candidate'
                    and observed['drawCandidate']['digest']==observed['digest']
                    and observed['drawCandidate']['index']==13
                    and not prompt_matches(data) and not closed_hand_face_mismatches(baseline,data,
                        {'handSlots':geometry['handSlots'],'drawSlot':geometry['drawSlot']},.5)
                    and friend_frame_stable(data,fresh_data))
            except (KeyError,TypeError,ValueError,OSError):
                good=False
            if not good and recovered_empty_pair(operator, baseline, receipt, observed, frame, captured, with_watch, started):
                operator.log('sanma_friend_nine_terminals_pass_recovery',
                             screenshots=[observed['screenshot'],observed['freshness']['screenshot']],
                             method='independent_recognition_of_fresh_capture',confirmed=False,
                             originalStart=started,operationAuthorized=False)
                if (operator.verified_friend_300_active is not True or not with_watch.alive()
                        or not 0<=time.monotonic()-started<300):
                    raise RuntimeError('friend continuity or deadline lost on pass recovery')
                transferred=True
                return with_watch
            if good:
                if (previous is not None and captured > previous[1]
                        and friend_frame_stable(Path(previous[0]).read_bytes(),data)):
                    if (not with_watch.alive() or operator.verified_friend_300_active is not True
                            or not 0<=time.monotonic()-started<300):
                        raise RuntimeError('friend continuity or deadline lost on pass recovery')
                    operator.log('sanma_friend_nine_terminals_pass_recovery',
                                 screenshots=[previous[0],observed['screenshot']],confirmed=False,
                                 originalStart=started,operationAuthorized=False)
                    transferred=True
                    return with_watch
                previous=(observed['screenshot'],captured)
            else:
                previous=None
            page.wait_for_timeout(500)
        raise RuntimeError('pass outcome not independently observed')
    finally:
        if not transferred:
            with_watch.close()
