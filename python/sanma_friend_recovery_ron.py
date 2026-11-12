"""Bounded terminal ron during an uncertain friend discard; never retries."""
import time


def execute_recovery_ron(operator, page, recovery, receipt, observation_started):
    actions = (receipt.get('candidates') or {}).get('candidates')
    if not isinstance(actions, list) or not any(isinstance(item, dict) and item.get('action') == 'ron' for item in actions):
        return None
    watch = recovery['watch']
    started = recovery['started']
    if (operator.verified_friend_300_active is not True or not watch.alive()
            or not started <= recovery['attempted_monotonic'] <= recovery['selected_monotonic'] < observation_started
            or not 0 <= (time.monotonic() - started) * 1000 < 300000):
        raise RuntimeError('discard recovery continuity, ordering or original deadline lost')
    operator._sanma_friend_resume_guard = (watch, started, 300000)
    try:
        # This is a terminal attempt, never proof of a win. The existing ron
        # implementation verifies the exact button layout, fresh pixels and
        # image-bound timing, and latches the target before its single click.
        return operator.execute_sanma_friend_ron_candidate(page, receipt)
    finally:
        operator._sanma_friend_resume_guard = None
