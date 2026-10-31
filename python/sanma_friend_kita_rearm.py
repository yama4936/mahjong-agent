"""Narrow, unverified visual evidence for a second friend-only north action."""
import hashlib
import io
from collections import Counter
from pathlib import Path
from PIL import Image, ImageChops, ImageStat
from sanma_friend_freshness import friend_action_target_key


def rearm_friend_kita_candidate(operator, before, after):
    """Rearm once on consistent hand, draw, and visible first-north changes.

    The unseen clock area, actual operation and replacement remain unverified.
    This is a CPU friend experiment, not game-state confirmation.
    """
    try:
        args=operator.args
        if (getattr(args,'experimental_sanma_friend',False) is not True or args.rules != 'sanma'
                or args.mode != 'force-auto' or args.action_deadline_ms != 300000
                or args.ranked_loop is not False or operator.verified_friend_300_active is not True): return False
        if getattr(operator,'_sanma_friend_kita_rearmed',False) is True: return False
        frames=[]; hands=[]
        for receipt in (before,after):
            if receipt.get('scope') != 'sanma_self_turn_observation' or receipt.get('operationAuthorized') is not False: return False
            fresh=receipt.get('freshness') or {}
            if (fresh.get('status') not in ('identical_pixels_candidate','stable_except_clock_candidate')
                    or fresh.get('operationAuthorized') is not False
                    or type(fresh.get('elapsedMs')) not in (int,float) or not 0 <= fresh['elapsedMs'] <= 20000): return False
            source=receipt.get('sourceObservation') or {};report=source.get('report') or {};digest=receipt.get('digest')
            if source.get('operationAuthorized') is not False or source.get('digest') != digest or report.get('digest') != digest: return False
            frame=Path(receipt['screenshot']).read_bytes()
            if hashlib.sha256(frame).hexdigest() != digest: return False
            h=report['hand']['value']; matches=h['matches']; tiles=h['tiles']
            if report['hand']['status'] != 'candidate' or len(tiles)!=14 or len(matches)!=14: return False
            if any(m.get('tile')!=tile for m,tile in zip(matches,tiles)):return False
            if any(m['confidence'] < .9 for m in matches if m['tile']=='N'):return False
            frames.append(frame);hands.append(h)
        pre,post=(Counter(h['tiles']) for h in hands)
        if pre['N'] < 2 or post['N'] != pre['N']-1 or pre-post != Counter({'N':1}): return False
        added=post-pre
        if sum(added.values()) != 1:return False
        tile=next(iter(added)); match=hands[1]['matches'][-1]
        if tile == 'N' or hands[1]['tiles'][-1] != tile or match['confidence'] < .95 or match['confidence']-match['runnerUpConfidence'] < .1:return False
        draw=after.get('drawCandidate') or {}
        if draw.get('status') != 'candidate' or draw.get('index') != 13 or draw.get('tile') != tile or draw.get('digest') != after.get('digest'):return False
        with Image.open(Path(__file__).parent/'fixtures'/'sanma-friend-first-north-visible.png') as reference:
            ref=reference.convert('RGB')
        similarities=[]
        for frame in frames:
            with Image.open(io.BytesIO(frame)) as image:
                if image.size != (1920,1080):return False
                part=image.convert('RGB').crop((1390,765,1425,850))
            similarities.append(1-sum(ImageStat.Stat(ImageChops.difference(part,ref)).mean)/765)
        if similarities[0] >= .95 or similarities[1] < .98:return False
        key=friend_action_target_key(frames[0],'kita');attempts=operator._sanma_friend_attempted_targets
        if not isinstance(attempts,set) or key not in attempts:return False
        attempts.remove(key)
        operator._sanma_friend_kita_rearmed=True
        operator.log('sanma_friend_kita_rearm_candidate', beforeDigest=before['digest'],afterDigest=after['digest'],
                     addedDraw=tile, visibleNorthSimilarities=similarities, confirmed=False,
                     risk='visual change and labels unverified; clock hides part of north; input success unknown')
        return True
    except (AttributeError,KeyError,TypeError,ValueError,OSError,IndexError):
        return False
