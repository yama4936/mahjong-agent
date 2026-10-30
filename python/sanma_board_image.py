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
    raw = recognize_board(image_path, sanma_compact_candidate=True, sanma_extra_score_retry=True)
    if 'tokens' not in raw:
        return {'verified': False, 'scope': 'sanma_offline_image_candidate',
                'reason': raw.get('reason', 'ocr_unavailable')}
    parsed = parse_sanma_board_tokens(raw['tokens'], expected_total_points=expected_total_points,
                                      payment_phase=payment_phase)
    return {**parsed, 'scope': 'sanma_offline_image_candidate', 'source': str(image_path),
            'tokens': raw['tokens'],
            **({'screenEvidence': raw['screenEvidence']} if 'screenEvidence' in raw else {})}


def observe_sanma_image(image_path: Path) -> dict:
    """Same unverified board and north observations as the CLI --with-north path."""
    from sanma_kita_image_experiment import detect_own_north_candidates
    from sanma_opposite_kita_experiment import opposite_north_candidate
    from sanma_left_kita_experiment import left_north_candidate
    board = recognize_sanma_board_candidate(image_path, expected_total_points=None, payment_phase=None)
    root = Path(__file__).resolve().parents[1] / 'test/fixtures'
    try:
        observations = {
            'own': detect_own_north_candidates(image_path, root / 'sanma-public-experiment/own-north-face.png'),
            'opposite': opposite_north_candidate(image_path, root / 'sanma-opposite-kita/north-glyph-reference.png',
                shadow_template_path=root / 'sanma-opposite-kita/north-glyph-shadow-reference.png'),
            'left': left_north_candidate(image_path, root / 'sanma-left-kita/left-north-reference.png',
                glare_template_path=root / 'sanma-left-kita/left-north-glare-reference.png'),
        }
        result = {'status': 'unknown', 'verified': False, 'complete': False, 'positions': observations}
    except Exception as error:
        result = {'status': 'unknown', 'verified': False, 'complete': False,
                  'reason': f'north observation failed: {error}'}
    return {'board': board, 'north': result}


if __name__ == '__main__':
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('screenshot', type=Path)
    parser.add_argument('--with-north', action='store_true')
    arguments = parser.parse_args()
    if arguments.with_north:
        print(json.dumps(observe_sanma_image(arguments.screenshot), ensure_ascii=False))
    else:
        board = recognize_sanma_board_candidate(arguments.screenshot, expected_total_points=None, payment_phase=None)
        print(json.dumps(board, ensure_ascii=False))
