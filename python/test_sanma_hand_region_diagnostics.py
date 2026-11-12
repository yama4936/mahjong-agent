"""Diagnostic attribution must never loosen the strict full-frame guard."""
import copy
import hashlib
import io
import unittest
from PIL import Image
from sanma_friend_freshness import REVIEWED_HAND_SLOTS, friend_frame_changes, friend_frame_stable


def png(image):
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


class HandRegionDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new('RGB', (1920,1080), (30,40,50))
        self.before = png(self.image)
        slots = [dict(zip(('x','y','width','height'), box)) for box in REVIEWED_HAND_SLOTS]
        self.report = {'digest':hashlib.sha256(self.before).hexdigest(), 'handGeometry':{
            'status':'candidate', 'value':{'viewport':{'width':1920,'height':1080},
            'handSlots':slots[:-1], 'drawSlot':slots[-1]}}}

    def compare_pixel(self, point, report=None):
        changed = self.image.copy()
        changed.putpixel(point, (31,40,50))
        after = png(changed)
        details = {}
        changes = friend_frame_changes(self.before, after, report=report, diagnostic=details)
        self.assertTrue(changes['fullFrame'])
        self.assertFalse(friend_frame_stable(self.before, after))
        return changes, details

    def test_background_attribution_without_weakening_guard(self):
        changes, details = self.compare_pixel((300,900), self.report)
        self.assertFalse(changes['hand'])
        self.assertTrue(details['handEnvelopeChanged'])
        self.assertTrue(details['handOutsideTilesChanged'])
        self.assertFalse(details['handTilesChanged'])
        self.assertFalse(details['operationAuthorized'])

    def test_every_slot_boundary_pixel_is_exactly_protected(self):
        for x,y,w,h in REVIEWED_HAND_SLOTS:
            for point in ((x,y), (x+w-1,y+h-1)):
                with self.subTest(point=point):
                    changes, details = self.compare_pixel(point, self.report)
                    self.assertTrue(changes['hand'])
                    self.assertTrue(details['handTilesChanged'])
                    self.assertFalse(details['handOutsideTilesChanged'])

    def test_button_and_raised_tile_changes_still_reject(self):
        for point in ((900,800), (300,875), (315,950), (1600,950)):
            with self.subTest(point=point):
                changes, _ = self.compare_pixel(point, self.report)
                if point == (900,800):
                    self.assertTrue(changes['actions'])

    def test_unknown_or_unbound_geometry_keeps_broad_hand(self):
        wrong_hash = copy.deepcopy(self.report); wrong_hash['digest'] = '0'*64
        moved = copy.deepcopy(self.report); moved['handGeometry']['value']['handSlots'][0]['x'] += 1
        missing = copy.deepcopy(self.report); missing['handGeometry']['value']['handSlots'].pop()
        unrecognized = copy.deepcopy(self.report); unrecognized['handGeometry']['status'] = 'unresolved'
        for report in (None, {}, wrong_hash, moved, missing, unrecognized):
            with self.subTest(report=report):
                changes, details = self.compare_pixel((300,900), report)
                self.assertTrue(changes['hand'])
                self.assertEqual(details['geometryStatus'], 'unreviewed_fallback')
                self.assertIsNone(details['handTilesChanged'])
                self.assertIsNone(details['handOutsideTilesChanged'])

    def test_original_interface_and_dimension_fail_closed(self):
        self.assertEqual(friend_frame_changes(self.before,self.before),
                         {'hand':False,'actions':False,'fullFrame':False,'clock':False})
        with self.assertRaises(ValueError):
            friend_frame_changes(self.before,png(Image.new('RGB',(960,540))),report=self.report)
