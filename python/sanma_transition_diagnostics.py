"""Read-only evidence capture after an unresolved sanma friend discard."""
import math
from pathlib import Path
import time


def capture_unresolved_discard(operator, page, recovery, now=time.monotonic):
    """Capture up to two independent observations; never authorize a move."""
    def active():
        try:
            start = recovery['started']
            deadline = operator.args.action_deadline_ms
            elapsed = (now() - start) * 1000
            return (operator.verified_friend_300_active is True
                    and recovery['watch'].alive() is True
                    and type(start) in (int, float) and math.isfinite(start)
                    and type(deadline) is int and deadline == 300000
                    and 0 <= elapsed < deadline)
        except Exception:
            return False

    for index in range(2):
        if not active():
            operator.log('sanma_friend_transition_diagnostic_stopped', reason='session_or_deadline',
                         observation=index, operationAuthorized=False)
            return
        try:
            observation = operator.inspect_sanma_self_turn(page)
            if not isinstance(observation, dict):
                raise ValueError('observation is not a receipt')
        except Exception as error:
            operator.log('sanma_friend_transition_diagnostic_stopped', reason='observation_failed',
                         error=str(error), observation=index, operationAuthorized=False)
            return
        valid = active()
        operator.log('sanma_friend_transition_diagnostic_observed', observation=index,
                     screenshot=observation.get('screenshot'), digest=observation.get('digest'),
                     receiptPath=(str(Path(observation['screenshot']).with_suffix('.receipt.json'))
                                  if isinstance(observation.get('screenshot'), str) else None), sessionValid=valid,
                     operationAuthorized=False)
        if not valid:
            operator.log('sanma_friend_transition_diagnostic_stopped', reason='session_or_deadline',
                         observation=index + 1, operationAuthorized=False)
            return
