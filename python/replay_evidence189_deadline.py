"""Read-only offline replay of evidence189; never connects to a browser.

Continuity is assumed ONLY to isolate saved evidence and deadline behavior.
Wall-clock/monotonic alignment is estimated from the recorded discard attempt.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sanma_friend_discard_recovery import candidate
from sanma_friend_freshness import check_friend_recovery_guard


def replay(root):
    events = [json.loads(line) for line in
              (root / 'operator.log').read_text().splitlines()]
    recovery = [event for event in events
                if event.get('event') == 'sanma_friend_discard_recovery_candidate'][-1]
    stopped = next(event for event in events
                   if event.get('reason') == 'discard_recovery_session_or_deadline')
    receipts = [json.loads(Path(path).with_suffix('.receipt.json').read_text())
                for path in recovery['screenshots']]
    for receipt in receipts:
        assert hashlib.sha256(Path(receipt['screenshot']).read_bytes()).hexdigest() == receipt['digest']
    start = recovery['originalStart']
    anchor = datetime.fromisoformat(recovery['journal'][0]['timestamp'])

    def monotonic_at(event):
        return recovery['attemptedMonotonic'] + (
            datetime.fromisoformat(event['timestamp']) - anchor).total_seconds()

    watch = SimpleNamespace(alive=lambda: True)
    accepted_time = monotonic_at(recovery)
    stop_time = monotonic_at(stopped)
    arguments = dict(continuity=watch, active=lambda: True, started=start, deadline_ms=300000)
    accepted = candidate(receipts[0], receipts[1:], recovery['journal'],
                         now=lambda: accepted_time, **arguments)
    expired = candidate(receipts[0], receipts[1:], recovery['journal'],
                        now=lambda: stop_time, **arguments)
    operator = SimpleNamespace(verified_friend_300_active=True,
                               _sanma_friend_resume_guard=(watch, start, 300000))
    with patch('time.monotonic', return_value=stop_time):
        try:
            check_friend_recovery_guard(operator)
            guard_rejected = False
        except RuntimeError:
            guard_rejected = True
    observations = [event for event in events if event.get('event') == 'sanma_self_turn_observed'
                    and recovery['timestamp'] < event['timestamp'] < stopped['timestamp']]
    result = {
        'scope': 'offline_saved_evidence_no_input',
        'continuity': 'assumed_for_replay_not_proven',
        'deadlineMs': 300000,
        'acceptedElapsedMsEstimate': round((accepted_time - start) * 1000),
        'stopElapsedMsEstimate': round((stop_time - start) * 1000),
        'savedEvidenceAcceptedBeforeDeadline': accepted,
        'savedEvidenceAcceptedAtStop': expired,
        'retainedGuardRejectedAtStop': guard_rejected,
        'freshnessAfterAcceptance': [event['freshness']['status'] for event in observations],
        'recordedStopReason': stopped['reason'],
        'recordedElapsedMs': stopped['deadlineElapsedMs'],
        'recordedContinuity': stopped['continuity'],
        'recordedFriendSessionActive': stopped['friendSessionActive'],
    }
    print(json.dumps(result, indent=2))
    return (accepted and not expired and guard_rejected
            and stopped['deadlineElapsedMs'] >= 300000
            and stopped['continuity']['invalid'] is False
            and stopped['friendSessionActive'] is True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence_root', type=Path)
    args = parser.parse_args()
    raise SystemExit(0 if replay(args.evidence_root) else 1)
