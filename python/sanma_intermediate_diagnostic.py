"""Associate a persisted intermediate observation with an uncertain discard.

Diagnostic only: no game-state or action conclusion is returned.
"""
import hashlib
import json
import math
from pathlib import Path
import time


def record(operator, recovery, receipt, observed_at, now=time.monotonic):
    try:
        started = recovery['started']
        selected = recovery['selected_monotonic']
        deadline = operator.args.action_deadline_ms
        def valid():
            return (operator.verified_friend_300_active is True
                    and recovery['watch'].alive() is True
                    and type(deadline) is int and deadline == 300000
                    and all(type(x) in (int, float) and math.isfinite(x) for x in (started, selected, observed_at))
                    and started <= selected < observed_at <= now()
                    and 0 <= (now() - started) * 1000 < deadline)
        if not valid():
            return
        image = Path(receipt['screenshot'])
        source = image.with_suffix('.receipt.json')
        if (json.loads(source.read_text()) != receipt
                or hashlib.sha256(image.read_bytes()).hexdigest() != receipt['digest']):
            return
        if not valid():
            return
        operator.log('sanma_friend_discard_intermediate_evidence',
                     screenshot=str(image), receiptPath=str(source), digest=receipt['digest'],
                     beforeDigest=recovery['before']['digest'], observedMonotonic=observed_at,
                     selectedMonotonic=selected, evidenceOnly=True, operationAuthorized=False)
    except Exception:
        return
