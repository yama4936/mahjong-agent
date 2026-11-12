"""Conservative correction for a witnessed 5-pixel detector-box truncation.

Only the specific 1920x1080 geometry pair observed in evidence191 is accepted.
This changes comparison crops, never click coordinates or receipt provenance.
"""

def aligned_post_slots(before, after):
    try:
        def slots(receipt):
            report = receipt['sourceObservation']['report']
            if report['handGeometry']['status'] != 'candidate':
                return None
            geometry = report['handGeometry']['value']
            return [*geometry['handSlots'], geometry['drawSlot']]
        old, new = slots(before), slots(after)
        if len(old) != 14 or len(new) != 14:
            return None
        if not all(s['y'] == 921 and s['height'] == 151 for s in old):
            return None
        if not all(s['y'] == 926 and s['height'] == 146 for s in new):
            return None
        if any(type(s[k]) is not int for s in old + new for k in ('x','y','width','height')):
            return None
        if any(not (0 <= s['x'] and 70 <= s['width'] <= 110 and s['x'] + s['width'] <= 1920) for s in old + new):
            return None
        # Narrowly bind this correction to the known full concealed-hand
        # layout, rejecting duplicate, reordered, shifted and overlapping boxes.
        expected_x = (223, 317, 412, 507, 602, 697, 792, 887, 981, 1076, 1171, 1266, 1361, 1486)
        for row in (old, new):
            if any(abs(s['x'] - x) > 1 or not 91 <= s['width'] <= 93
                   for s, x in zip(row, expected_x)):
                return None
            if any(a['x'] + a['width'] > b['x'] for a, b in zip(row, row[1:])):
                return None
        if any(abs(a['x'] - b['x']) > 1 or abs(a['width'] - b['width']) > 2
               for a, b in zip(old, new)):
            return None
        return [dict(s, y=921, height=151) for s in new]
    except (KeyError, TypeError, ValueError):
        return None
