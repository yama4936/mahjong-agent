# Anonymized right-river detection fixtures

These two 305×250 crops retain only the calibrated right discard region of saved CPU friend-match screenshots, at original 1920×1080 coordinates (1115, 285)–(1420, 535). They contain no player names, avatars, or account identifiers. `empty.png` shows no right-river tiles; `four.png` shows four visible tiles (top to bottom: white, 1s, 1m, 9m). The latter includes highlighting, as in the source image.

The portable test places each crop on a black 1920×1080 canvas and uses a stub classifier. It verifies candidate-region detection and unknown-state propagation, not recognition of tile identity or completeness. Separate tests using the real classifier remain conditional on the model and full-size source screenshots.
