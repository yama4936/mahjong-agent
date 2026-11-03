"""Offline state-machine experiment for a possibly completed sanma discard.

Inputs are retained receipts and an operation journal, not certified messages.
The terminal candidate state never confirms a discard or authorizes input.
"""
import json
import re
from collections import Counter
from pathlib import Path
from datetime import datetime
from sanma_river_cell_diagnostic import compare as compare_cells
from sanma_discard_glyph_diagnostic import compare as compare_glyph


def _right_north_additions(before, posts):
    """Conservative image candidates for newly exposed right-side norths.

    Empty candidate lists alone do not establish absence; require each prior
    glyph crop to lack a light tile face and both later crops to show one.
    """
    from PIL import Image
    from sanma_right_kita_experiment import right_north_candidate
    root = Path(__file__).parent / 'fixtures'
    templates = [root / f'sanma-right-north-c177-{s}.png' for s in ('top','bottom')]
    boxes = ((1410,214,1455,239),(1418,247,1463,272))
    try:
        frames = [before, *posts]
        readings = [right_north_candidate(Path(r['screenshot']), templates) for r in frames]
        if any(x.get('frame_sha256') != r['digest'] for x,r in zip(readings,frames)):
            return 0
        slots = [{c['slot'] for c in x.get('candidates', [])} for x in readings]
        added = slots[1] - slots[0]
        if not added or slots[2] - slots[0] != added or not added <= {0,1}:
            return 0
        with Image.open(before['screenshot']) as source:
            baseline = source.convert('RGB')
        later = []
        for post in posts:
            with Image.open(post['screenshot']) as source:
                later.append(source.convert('RGB'))
        for slot in added:
            light = lambda image: sum(min(pixel) > 180 for pixel in image.crop(boxes[slot]).getdata())
            if light(baseline) > 100 or any(light(image) < 500 for image in later):
                return 0
        return len(added)
    except (KeyError, TypeError, ValueError, OSError, IndexError, ImportError):
        return 0


def _read(path):
    source = Path(path)
    result = json.loads(source.read_text())
    image = Path(result['screenshot'])
    if not image.is_absolute():
        result['screenshot'] = str((source.parent / image).resolve())
    return result


def _time(item):
    result = datetime.fromisoformat(item['timestamp'])
    if result.tzinfo is None:
        raise ValueError('timezone required')
    return result


def _frame_time(path):
    name = Path(path).name
    match = re.match(r'^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2}\.\d+)([+-]\d{2})-(\d{2})\.', name)
    if not match:
        raise ValueError('timestamped capture filename required')
    date, hour, minute, second, zone_hour, zone_minute = match.groups()
    return datetime.fromisoformat(f'{date}T{hour}:{minute}:{second}{zone_hour}:{zone_minute}')


def evaluate(before_path, after_paths, journal, *, recheck_round=False):
    """Cross-check retained evidence; caller must preserve provenance and order."""
    result = {'scope': 'offline_untrusted_sanma_discard_evidence_chain',
              'state': 'pending', 'confirmed': False, 'operationAuthorized': False,
              'failures': [], 'evidence': {},
              'limitations': ['journal and recognition claims are not authenticated',
                              'round and turn are image candidates, not verified state',
                              'physical append does not establish input causality',
                              'glyph distance is measured only, not a tile identity verdict',
                              'calls and coincidental repeated rounds remain unresolved']}
    def reject(reason):
        result['failures'].append(reason)
        return result
    try:
        if len(after_paths) < 2 or len(journal) != 2:
            return reject('two observations and attempted/selection journal required')
        attempt, selection = journal
        if (attempt.get('status') != 'attempted' or selection.get('status') != 'selection_confirmed'
                or selection.get('result') != 'discard_not_verified'
                or _time(attempt) > _time(selection)):
            return reject('invalid action journal')
        for key in ('tile', 'clickIndex', 'clickPoint', 'frameSha256'):
            if attempt.get(key) is None or attempt.get(key) != selection.get(key):
                return reject('journal mismatch')
        before = _read(before_path)
        posts = [_read(p) for p in after_paths]
        if recheck_round:
            from sanma_round_fresh_ocr import check_round
            if not all(check_round(p) for p in [before, *posts]):
                return reject('fresh frame-bound round OCR unavailable or disagrees')
        times = [_frame_time(p['screenshot']) for p in [before, *posts]]
        if (not times[0] <= _time(attempt) <= _time(selection) < times[1]
                or any(a >= b for a, b in zip(times[1:], times[2:]))
                or len({p['digest'] for p in posts}) != len(posts)):
            return reject('capture order or distinct observations invalid')
        if before['digest'] != attempt['frameSha256']:
            return reject('journal frame mismatch')
        if any(p['digest'] != p['sourceObservation']['digest'] for p in [before, *posts]):
            return reject('receipt frame mismatch')
        report = before['sourceObservation']['report']
        geometry = report['handGeometry']
        hand = report['hand']
        index = attempt['clickIndex']
        if (geometry.get('status') != 'candidate' or hand.get('status') != 'candidate'
                or type(index) is not int or index < 0):
            return reject('missing selected hand position')
        geometry_value, hand_value = geometry['value'], hand['value']
        points, tiles, matches = (geometry_value['clickPoints'], hand_value['tiles'], hand_value['matches'])
        if (index >= len(points) or index >= len(tiles) or index >= len(matches)
                or points[index] != attempt['clickPoint'] or tiles[index] != attempt['tile']
                or matches[index].get('tile') != attempt['tile']):
            return reject('selected index, point and hand candidate mismatch')
        physical = [compare_cells(before['screenshot'], p['screenshot']) for p in posts]
        if any(x['beforeSha256'] != before['digest'] or x['afterSha256'] != p['digest']
               for x, p in zip(physical, posts)):
            return reject('image hash mismatch')
        if not all(x['singlePhysicalAppendCandidate'] for x in physical):
            return reject('physical append absent or uncertain')
        indices = [x['emptyToTileIndices'][0] for x in physical]
        if len(set(indices)) != 1:
            return reject('inconsistent physical append position')
        stability = compare_cells(posts[0]['screenshot'], posts[-1]['screenshot'])
        if (not stability['existingTilesUnchangedCandidate'] or stability['emptyToTileIndices']
                or [x['state'] for x in stability['beforeCells']] != [x['state'] for x in stability['afterCells']]):
            return reject('post-action physical river unstable')
        boards = [p['sourceObservation']['board'].get('candidate') for p in [before, *posts]]
        if not all(isinstance(x, dict) for x in boards):
            return reject('missing board candidates')
        for key in ('seat', 'round', 'honba', 'scores'):
            if boards[0].get(key) is None or any(board.get(key) != boards[0][key] for board in boards[1:]):
                return reject('board candidate changed or missing')
        remaining = [x.get('remainingTiles') for x in boards]
        extra = _right_north_additions(before, posts) if all(type(x) is int for x in remaining) and remaining[0] - remaining[1] > 3 else 0
        if (any(type(x) is not int for x in remaining) or not all(0 <= x <= 70 for x in remaining)
                or not all(0 < remaining[0] - x <= 3 + extra for x in remaining[1:])
                or len(set(remaining[1:])) != 1):
            return reject('remaining count not consistent with later candidate turn')
        glyphs = [compare_glyph(before_path, p, attempt['clickIndex']) for p in after_paths]
        if not all(x['exactSingleAppendCandidate'] and x['appendedTileCandidate'] == attempt['tile']
                   and x['glyphDistance'] is not None for x in glyphs):
            return reject('river tile candidate or glyph measurement unavailable')
        draws = [p.get('drawCandidate') for p in posts]
        if not all(isinstance(d, dict) and d.get('status') == 'candidate' and d.get('digest') == p['digest']
                   and d.get('index') == 13 and isinstance(d.get('tile'), str) for d, p in zip(draws, posts)):
            return reject('missing repeated draw candidates')
        if len({d['tile'] for d in draws}) != 1:
            return reject('draw candidate changed')
        # A closed hand on a later turn must equal the previously observed
        # fourteen tiles less the selected tile plus the subsequent draw. This
        # is an additional consistency check, not proof: both observations can
        # contain the same recognition error and open calls remain unresolved.
        before_tiles = hand_value.get('tiles')
        if (hand_value.get('candidateMelds') != 0 or not isinstance(before_tiles, list)
                or len(before_tiles) != 14 or not all(isinstance(t, str) for t in before_tiles)):
            return reject('missing full previous hand')
        expected = Counter(before_tiles)
        expected[attempt['tile']] -= 1
        expected += Counter([draws[0]['tile']])
        for post in posts:
            post_hand = post['sourceObservation']['report']['hand']
            value = post_hand.get('value')
            if (post_hand.get('status') != 'candidate' or not isinstance(value, dict)
                    or value.get('candidateMelds') != 0
                    or not isinstance(value.get('tiles'), list) or len(value['tiles']) != 14
                    or not all(isinstance(t, str) for t in value['tiles'])
                    or Counter(value['tiles']) != expected):
                return reject('closed hand conservation failed or unavailable')
        result['state'] = 'later_turn_evidence_candidate'
        result['evidence'] = {'selectedTile': attempt['tile'], 'selectedIndex': attempt['clickIndex'],
                              'cellIndex': indices[0], 'remainingCandidates': remaining,
                              'glyphDistances': [x['glyphDistance'] for x in glyphs],
                              'beforeSha256': before['digest'], 'afterSha256': [p['digest'] for p in posts],
                              'drawTileCandidate': draws[0]['tile']}
        return result
    except (KeyError, TypeError, ValueError, OSError, IndexError) as error:
        return reject(f'invalid evidence: {type(error).__name__}: {error}')
