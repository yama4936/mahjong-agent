"""Read-only, untrusted sanma scoreboard candidate from a saved image.

This combines the existing calibrated OCR probe with the sanma token parser.
It does not establish that the game is sanma, the room total, the payment
phase, screen identity, or OCR correctness; callers must not use its result
for live decisions or clicks.
"""
from pathlib import Path

from board_metadata import recognize_board, parse_sanma_board_tokens


def recognize_sanma_board_candidate(image_path: Path, *, expected_total_points: int | None,
                                    payment_phase: str | None) -> dict:
    raw = recognize_board(image_path)
    if 'tokens' not in raw:
        return {'verified': False, 'scope': 'sanma_offline_image_candidate',
                'reason': raw.get('reason', 'ocr_unavailable')}
    parsed = parse_sanma_board_tokens(raw['tokens'], expected_total_points=expected_total_points,
                                      payment_phase=payment_phase)
    return {**parsed, 'scope': 'sanma_offline_image_candidate', 'source': str(image_path),
            'tokens': raw['tokens']}
