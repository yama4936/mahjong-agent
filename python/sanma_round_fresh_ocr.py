"""Untrusted same-frame OCR check, used for offline sanma diagnostics only."""
import hashlib
import math
import re
from pathlib import Path

from board_metadata import recognize_board


def check_round(receipt):
    """Reject absent, conflicting, stale or unreadable round observations.

    A matching OCR candidate is not proof of same hand, round or session.
    """
    try:
        path = Path(receipt['screenshot'])
        frame = path.read_bytes()
        digest = hashlib.sha256(frame).hexdigest()
        if receipt.get('digest') != digest or receipt['sourceObservation'].get('digest') != digest:
            return False
        expected = receipt['sourceObservation']['board']['candidate']['round']
        if expected not in {f'{wind}_{number}' for wind in ('east', 'south', 'west', 'north') for number in (1, 2, 3)}:
            return False
        sink = []
        result = recognize_board(path, sanma_compact_candidate=True, _rgb_sink=sink, _frame_bytes=frame)
        if not sink or sink[0][1] != digest or not isinstance(result.get('tokens'), list):
            return False
        matches = []
        plausible = []
        for token in result['tokens']:
            if not isinstance(token, dict):
                return False
            text, confidence, x, y = (token.get(k) for k in ('text', 'confidence', 'x', 'y'))
            if (isinstance(text, str) and re.fullmatch('[東南西北][1-3]局', text)
                    and type(confidence) in (int, float) and math.isfinite(confidence) and 0 <= confidence <= 1
                    and type(x) in (int, float) and type(y) in (int, float)
                    and math.isfinite(x) and math.isfinite(y) and abs(x - 960) <= 24 and abs(y - 405) <= 20):
                plausible.append(text)
                if confidence >= .98:
                    matches.append(text)
        if len(matches) != 1 or any(text != matches[0] for text in plausible):
            return False
        return f"{dict(東='east', 南='south', 西='west', 北='north')[matches[0][0]]}_{matches[0][1]}" == expected
    except Exception:
        return False
