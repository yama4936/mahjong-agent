"""Replay retained evidence189 pre-click rejections; no browser or input.

Run with PYTHONPATH=python and the project's image/recognition dependencies.
Requires the local evidence189 archive, which is not included in the repository.
Defaults to this workstation's SSD path; use --source-root for a relocated copy.
Hashes bind logs, screenshots and retained reports; recognition is not rerun.
"""
import argparse
import hashlib
import json
from pathlib import Path

from auto_operator import experimental_draw_glyph_stability
from sanma_friend_freshness import friend_frame_stable

LOG_SHA = 'eace4efe3f34df212de457e3e588f707e88c6f0a96de26a6c68d2c0a707dcbfa'
DEFAULT_ROOT = Path('/home/yama1/server/data/dev-work/jantama/evidence189')


def checked(path, expected):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f'SHA256 mismatch: {path}')
    return data


def source_path(root, absolute):
    original = Path(absolute)
    return root / original.relative_to(DEFAULT_ROOT)


def replay(root=DEFAULT_ROOT):
    if not __debug__:
        raise RuntimeError('optimized execution is unsupported: replay requires assertions')
    rows = [json.loads(row) for row in checked(root / 'operator.log', LOG_SHA).splitlines()]
    recoveries = [i for i, row in enumerate(rows) if row['event'] == 'sanma_friend_discard_recovery_candidate']
    last = recoveries[-1]
    assert last == 150 and not rows[last]['confirmed'] and not rows[last]['operationAuthorized']
    cases = []
    for i in range(last + 1, len(rows)):
        event = rows[i]
        if event['event'] != 'sanma_friend_discard_preclick_rejected':
            continue
        assert event['operationAuthorized'] is False
        failure = rows[i+1]
        assert failure['event'] == 'sanma_friend_discard_experiment' and failure['status'] == 'blocked'
        observation = next(row for row in rows[last+1:i] if row['event'] == 'sanma_self_turn_observed'
                           and row['digest'] == event['referenceSha256'])
        before = checked(source_path(root, event['referenceScreenshot']), event['referenceSha256'])
        after = checked(source_path(root, event['screenshot']), event['sha256'])
        receipt = json.loads(checked(source_path(root, observation['receiptPath']), observation['receiptSha256']))
        assert receipt['digest'] == event['referenceSha256']
        assert friend_frame_stable(before, after) is False
        diag, errors = {}, []
        accepted = experimental_draw_glyph_stability(before, after, receipt['sourceObservation']['report'],
                                                       diagnostic=diag, on_wall_error=errors.append)
        assert accepted is False and not errors
        assert diag == failure['preclickDiagnostic'], (i+1, diag, failure['preclickDiagnostic'])
        cases.append({'line': i+1, 'referenceSha256': event['referenceSha256'],
                      'rejectedSha256': event['sha256'], 'diagnostic': diag})
    assert [x['line'] for x in cases] == [190, 235, 243]
    stop = next(row for row in reversed(rows) if row['event'] == 'sanma_friend_stopped')
    assert stop['reason'] == 'discard_recovery_session_or_deadline'
    return {'offlineOnly': True, 'operationAuthorized': False, 'lastRecoveryLine': last+1,
            'cases': cases, 'stopReason': stop['reason'], 'deadlineElapsedMs': stop['deadlineElapsedMs'],
            'limitations': ['Uses original recognition reports rather than rerunning recognition.',
              'A rejection stage does not establish its physical cause.',
              'No live input, evidence of a completed automatic match, or ranked assessment.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=DEFAULT_ROOT)
    print(json.dumps(replay(parser.parse_args().source_root), ensure_ascii=False, indent=2))
