"""Read-only, untrusted sanma scoreboard candidate from a saved image.

This combines the existing calibrated OCR probe with the sanma token parser.
It does not establish that the game is sanma, the room total, the payment
phase, screen identity, or OCR correctness; callers must not use its result
for live decisions or clicks.
"""
from pathlib import Path

from board_metadata import recognize_board, parse_sanma_board_tokens


def recognize_sanma_board_candidate(image_path: Path, *, expected_total_points: int | None,
                                    payment_phase: str | None, _rgb_sink=None, _frame_bytes=None) -> dict:
    raw = recognize_board(image_path, sanma_compact_candidate=True, sanma_extra_score_retry=True,
                          **({"_rgb_sink": _rgb_sink, "_frame_bytes": _frame_bytes} if _rgb_sink is not None else {}))
    if 'tokens' not in raw:
        return {'verified': False, 'scope': 'sanma_offline_image_candidate',
                'reason': raw.get('reason', 'ocr_unavailable')}
    parsed = parse_sanma_board_tokens(raw['tokens'], expected_total_points=expected_total_points,
                                      payment_phase=payment_phase)
    return {**parsed, 'scope': 'sanma_offline_image_candidate', 'source': str(image_path),
            'tokens': raw['tokens'],
            **({'screenEvidence': raw['screenEvidence']} if 'screenEvidence' in raw else {})}


def observe_sanma_image(image_path: Path, *, expected_sha256: str | None = None, _frame_bytes: bytes | None = None) -> dict:
    """Same unverified board and north observations as the CLI --with-north path."""
    from sanma_kita_image_experiment import detect_own_north_candidates, detect_own_partial_north_candidate
    from sanma_opposite_kita_experiment import opposite_north_candidate
    from sanma_left_kita_experiment import left_north_candidate
    from sanma_right_kita_experiment import right_north_candidate
    rgb_sink = []
    board = recognize_sanma_board_candidate(image_path, expected_total_points=None, payment_phase=None, _rgb_sink=rgb_sink, _frame_bytes=_frame_bytes)
    if expected_sha256 is not None and (not rgb_sink or rgb_sink[0][1] != expected_sha256):
        raise ValueError('board frame digest mismatch')
    root = Path(__file__).resolve().parents[1] / 'test/fixtures'
    try:
        import cv2
        if _frame_bytes is None:
            image_gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        else:
            import numpy as np
            image_gray = cv2.imdecode(np.frombuffer(_frame_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            if image_gray is None:
                raise ValueError('frame decode failed')
        immutable_digest = rgb_sink[0][1] if _frame_bytes is not None else None
        observations = {
            'own': {**detect_own_north_candidates(image_path, root / 'sanma-public-experiment/own-north-face.png', image_gray=image_gray, _immutable_sha256=immutable_digest),
                'partialObservation': detect_own_partial_north_candidate(image_path, Path(__file__).parent / 'fixtures/sanma-own-north-partial-c177.png',
                                                                   image_rgb=rgb_sink[0][0] if rgb_sink else None,
                                                                   expected_sha256=rgb_sink[0][1] if rgb_sink else None,
                                                                   _immutable_sha256=immutable_digest)},
            'opposite': opposite_north_candidate(image_path, root / 'sanma-opposite-kita/north-glyph-reference.png',
                shadow_template_path=root / 'sanma-opposite-kita/north-glyph-shadow-reference.png', image_gray=image_gray, _immutable_sha256=immutable_digest),
            'left': left_north_candidate(image_path, root / 'sanma-left-kita/left-north-reference.png',
                glare_template_path=root / 'sanma-left-kita/left-north-glare-reference.png', image_gray=image_gray, _immutable_sha256=immutable_digest),
            'right': right_north_candidate(image_path, [Path(__file__).parent / f'fixtures/sanma-right-north-c177-{label}.png'
                                                        for label in ('top', 'bottom')], image_gray=image_gray, _immutable_sha256=immutable_digest),
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
