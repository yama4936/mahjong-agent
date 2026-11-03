# Experimental unclassified draw recovery

This CPU friend 300+0 path treats a blank draw as an unknown physical tile,
not an identified white dragon. The image cannot distinguish a white tile from
an unloaded face. The journal keeps `blankDrawIdentityUnknown`; recovery
requires two consistent later frames, retained closed-hand faces, one physical
river append, same board candidates, plausible wall-count decrease, the
original action deadline and a live continuity guard. It does not use the
appended tile label or assert input causality. Any missing evidence stops play.

The positive replay uses the real evidence149 tsumogiri trajectory with the
blank draw from evidence163 composited into the initial frame. Board candidates
were manually supplied from the visible display because evidence149 used an
unsupported camera layout. This is synthetic evidence, not an actual blank
physical discard and not validation of end-to-end OCR or live recovery. The
negative replays include a correctly hashed later image without the expected
river append, changed hand/round/remaining count, inconsistent journal flags,
and expiry of the original deadline. Actual live 300+0 regression remains
necessary before assessing operational effectiveness; no ranked performance is
established by these tests.
