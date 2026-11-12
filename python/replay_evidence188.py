"""Replay all 16 evidence188 observation pairs offline, with SHA-bound originals.

Run: python -B python/replay_evidence188.py [--source-root PATH].
Missing or altered evidence fails; no browser connection or input is performed.
"""
import argparse
import hashlib
import json
from pathlib import Path

from sanma_friend_freshness import friend_frame_changes, friend_frame_stable
from sanma_friend_pon_stability import pon_pass_stability

FIXTURES = Path(__file__).parent / 'fixtures' / 'evidence188'


def checked_bytes(root, item):
    path = root / item['path']
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != item['sha256']:
        raise AssertionError(f'evidence SHA256 mismatch: {path}')
    return data


def replay(source_root=None):
    from auto_operator import experimental_kita_glyph_stability, experimental_draw_glyph_stability

    manifest = json.loads((FIXTURES / 'manifest.json').read_text())
    root = Path(source_root or manifest['sourceRootDefault'])
    rows = [json.loads(line) for line in checked_bytes(root, manifest['sourceLog']).splitlines()]
    observations = [i for i, row in enumerate(rows, 1) if row['event'] == 'sanma_self_turn_observed']
    assert observations == [case['line'] for case in manifest['cases']]
    assert len(observations) == 16
    waits = [row for row in rows if row['event'] == 'sanma_friend_wait']
    assert [row['streak'] for row in waits] == list(range(1, 17))
    assert all(row['reason'] == 'observation_changed_reobserve' for row in waits)
    assert waits[0]['elapsedSeconds'] == 0 and waits[-1]['elapsedSeconds'] == 123.31
    assert rows[-1]['event'] == 'sanma_friend_stopped'
    assert rows[-1]['reason'] == 'observation_changed_timeout' and rows[-1]['streak'] == 16
    start = next(row for row in rows if row['event'] == 'sanma_friend_start_input_sent')
    assert start['actionDeadlineMs'] == 300000 and start['roomClock'] == '300+0'
    # This establishes absence in this recorded log, not absence of unlogged input.
    recorded_inputs = [row['event'] for row in rows
                       if 'input_sent' in row['event'] or 'clicked' in row['event']]
    assert recorded_inputs == ['sanma_friend_start_input_sent', 'sanma_friend_start_clicked']
    results = []
    for case in manifest['cases']:
        before = checked_bytes(root, case['before'])
        after = checked_bytes(root, case['after'])
        receipt = json.loads(checked_bytes(root, case['receipt']))
        report = receipt['sourceObservation']['report']
        historical = rows[case['line'] - 1]
        freshness = historical['freshness']
        assert freshness['status'] == 'changed' and freshness['operationAuthorized'] is False
        assert {**freshness['regionsChanged'], 'clock': freshness['clockChanged']} == case['expectedChanges']
        assert freshness['handRegionDiagnostics'] == case['expectedDiagnostic']
        assert {k: v for k, v in freshness['guards']['pon'].items()
                if k not in ('outcome', 'elapsedMs')} == case['expectedPonDiagnostic']
        assert freshness['guards']['pon']['outcome'] == 'rejected'
        assert historical['digest'] == case['before']['sha256'] == receipt['digest']
        assert historical['freshness']['digest'] == case['after']['sha256']
        diagnostic = {}
        changes = friend_frame_changes(before, after, report=report, diagnostic=diagnostic)
        assert changes == case['expectedChanges'], (case['line'], changes)
        assert diagnostic == case['expectedDiagnostic'], (case['line'], diagnostic)
        assert not friend_frame_stable(before, after)
        pon_diagnostic, errors = {}, []
        accepted = pon_pass_stability(before, after, report, diagnostic=pon_diagnostic,
                                      on_wall_error=errors.append)
        assert not accepted, case['line']
        assert pon_diagnostic == case['expectedPonDiagnostic'], (case['line'], pon_diagnostic)
        assert not errors, (case['line'], errors)
        other_guards = {}
        for name, guard in [('kita', experimental_kita_glyph_stability),
                            ('draw', experimental_draw_glyph_stability)]:
            guard_diagnostic, guard_errors = {}, []
            guard_accepted = guard(before, after, report, diagnostic=guard_diagnostic,
                                   on_wall_error=guard_errors.append)
            assert not guard_accepted and not guard_errors, (case['line'], name, guard_errors)
            # The runtime caller adds the outcome for ordinary False returns.
            guard_diagnostic.setdefault('outcome', 'rejected')
            expected = {k: v for k, v in freshness['guards'][name].items() if k != 'elapsedMs'}
            assert {k: v for k, v in guard_diagnostic.items() if k != 'elapsedMs'} == expected, (
                case['line'], name, guard_diagnostic, expected)
            other_guards[name] = {'accepted': guard_accepted, 'diagnostic': guard_diagnostic}
        results.append({'line': case['line'], 'changes': changes, 'diagnostic': diagnostic,
                        'ponAccepted': accepted, 'ponDiagnostic': pon_diagnostic,
                        'otherGuards': other_guards})
    return {'offlineOnly': True, 'operationAuthorized': False,
            'recordedWaitCount': len(waits), 'recordedWaitElapsedSeconds': 123.31,
            'recordedStopReason': rows[-1]['reason'], 'recordedInputEvents': recorded_inputs,
            'sourceSettings': manifest['sourceSettings'], 'cases': results,
            'limitations': ['Replays saved reports; does not re-run recognition.',
                            'Guard rejection stages do not establish the physical cause of pixel changes.',
                            'No live match, browser lifecycle reproduction, or ranked evaluation performed.',
                            'Match completion is unconfirmed.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path)
    args = parser.parse_args()
    print(json.dumps(replay(args.source_root), ensure_ascii=False, indent=2))
