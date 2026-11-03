"""Boundary checks for the optional friend-only wall lighting predicate."""
import unittest
from PIL import Image, ImageDraw
from auto_operator import _sanma_draw_wall_edge_lighting


class WallThresholds(unittest.TestCase):
    @staticmethod
    def candidate(x, y, count, delta, *, lamp=0, seam=False, isolated=False):
        a = Image.new('RGB', (1920, 1080), (125,125,125))
        b = a.copy()
        da, db = ImageDraw.Draw(a), ImageDraw.Draw(b)
        if isolated:
            # A disconnected 5 x 4 mark cannot be explained by a shifted edge.
            da.rectangle((x+8,y+8,x+12,y+11), fill=(119,)*3)
            db.rectangle((x+8,y+8,x+12,y+11), fill=(119+delta,)*3)
        elif seam:
            for i in range(count):
                a.putpixel((x+i,y+21),(119,)*3)
                b.putpixel((x+i,y+21),(119+delta,)*3)
        else:
            # A one-pixel shift along a pre-existing vertical wall edge.
            da.rectangle((x,y,x+15,y+31),fill=(119,)*3)
            db.rectangle((x,y,x+15,y+31),fill=(119,)*3)
            for i in range(count):
                b.putpixel((x+15,y+i),(119+delta,)*3)
        if lamp:
            db.rectangle((890,495,1014,515),fill=(125+lamp,)*3)
        masks=[im.convert('L').point(lambda v:255 if v<120 else 0) for im in (a,b)]
        return _sanma_draw_wall_edge_lighting(a,b,*masks,x,y,count)

    def test_count_and_rgb_limits(self):
        for n,expected in ((14,False),(15,True),(20,True),(21,False)):
            with self.subTest(n=n):self.assertEqual(self.candidate(288,320,n,12),expected)
        self.assertTrue(self.candidate(288,320,15,12))
        self.assertFalse(self.candidate(288,320,15,13))

    def test_seam_limits_and_outside_edge(self):
        self.assertTrue(self.candidate(320,96,17,18,seam=True))
        self.assertFalse(self.candidate(320,96,17,19,seam=True))
        self.assertFalse(self.candidate(288,320,20,12,isolated=True))
        self.assertFalse(self.candidate(992,384,15,12))

    def test_lamp_limit(self):
        self.assertTrue(self.candidate(288,320,15,12,lamp=1))
        self.assertFalse(self.candidate(288,320,15,12,lamp=2))


if __name__ == '__main__':
    unittest.main()
