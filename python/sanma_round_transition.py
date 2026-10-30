"""Offline structural checks for one sanma hand transition; never authorizes play."""
import re
from typing import Any

_WINDS = ('east', 'south', 'west')


def _snapshot(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, dict) or value.get('verified') is not True:
        return None
    round_name, seat, honba = value.get('round'), value.get('seat'), value.get('honba')
    if not isinstance(round_name, str) or seat not in _WINDS or type(honba) is not int or honba < 0:
        return None
    match = re.fullmatch(r'(east|south)_([1-3])', round_name)
    if match is None:
        return None
    return ((0 if match[1] == 'east' else 3) + int(match[2]) - 1, _WINDS.index(seat), honba)


def possible_sanma_hand_transition(
    previous: Any, current: Any, *, same_match_verified: bool, exactly_one_hand_verified: bool,
    match_length: str,
) -> bool:
    """Check necessary structural conditions, not proof that a new hand exists.

    Callers must independently verify both board snapshots, their match identity,
    and that exactly one hand elapsed. This does not check frame independence,
    results, terminal state, river reset, friend settings, or authorize clicks.
    East-only matches fail closed on east-3 to south-1 (extensions unknown).
    A drawn hand may rotate the dealer with honba incremented; a nondealer win
    may rotate with honba reset. Further event-specific evidence is required.
    """
    if same_match_verified is not True or exactly_one_hand_verified is not True \
            or match_length not in ('east', 'south'):
        return False
    before, after = _snapshot(previous), _snapshot(current)
    if before is None or after is None:
        return False
    before_round, before_seat, before_honba = before
    after_round, after_seat, after_honba = after
    if match_length == 'east' and (before_round >= 3 or after_round >= 3):
        return False
    if after_round == before_round:
        return after_seat == before_seat and after_honba == before_honba + 1
    if after_round != before_round + 1:
        return False
    return after_seat == (before_seat - 1) % 3 and after_honba in (0, before_honba + 1)
