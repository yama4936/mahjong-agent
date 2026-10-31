"""Select a review candidate from chronological room screenshots, without input.

Provide separate captures in chronological order. This tool cannot establish
that frames were captured independently or in the stated order. Selection does
not verify CPU slots or authorize a start. The chosen original image must still
be reviewed, and the normal fresh-frame start check applies.
"""
import argparse
import hashlib
import json
from pathlib import Path

from friend_start import verified_friend_room


def select_preflight_candidate(frames: list[bytes], *, sanma: bool) -> tuple[int, list[int]]:
    """Select the frame matching most peers, including two adjacent peers.

    Each pair uses the existing full room comparator. The two matching peers
    must be distinct from the candidate, and adjacent in the capture order.
    This only ranks evidence; it does not establish the room's settings.
    """
    if len(frames) < 3 or len(frames) > 8:
        raise ValueError('provide 3 to 8 room frames in capture order')
    scores = []
    for i, candidate in enumerate(frames):
        matches = [j for j, frame in enumerate(frames)
                   if j != i and verified_friend_room(frame, candidate, sanma=sanma)]
        if any(j + 1 in matches for j in matches):
            scores.append((len(matches), -i, i, matches))
    if not scores:
        raise ValueError('no candidate has two consecutive independently matching frames')
    _, _, index, matches = max(scores)
    return index, matches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sanma', action='store_true')
    parser.add_argument('frames', nargs='+', type=Path, help='3 to 8 separate screenshots in capture order; independence and order are not verified')
    args = parser.parse_args()
    frames = [path.read_bytes() for path in args.frames]
    index, matches = select_preflight_candidate(frames, sanma=args.sanma)
    print(json.dumps({'candidate': str(args.frames[index]), 'sha256': hashlib.sha256(frames[index]).hexdigest(),
                      'matchingFrames': [str(args.frames[j]) for j in matches],
                      'requiresHumanReview': True, 'operationAuthorized': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
