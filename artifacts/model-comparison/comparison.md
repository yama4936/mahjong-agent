# Mahjong tile recognition model comparison

Generated: 2026-09-20T07:12:41Z

Softmax scores are uncalibrated. No result is an Auto-operation certificate.

## live-all-7-correlated-frames

| Model | Exact | Non-red exact | Red exact | Complete frames | ms/crop |
| --- | ---: | ---: | ---: | ---: | ---: |
| cvmaj+automajsoul-red-gate | 96/96 (100.0%) | 90/90 | 6/6 | 5/5 | 1.0 |
| cvmaj-cnn34 | 90/96 (93.8%) | 90/90 | 0/6 | 0/5 | 0.1 |
| current-template-face-lofo | 86/96 (89.6%) | 80/90 | 6/6 | 0/5 | — |
| automajsoul-tilenet38 | 83/96 (86.5%) | 77/90 | 6/6 | 4/5 | 0.9 |
| pjura-vit34 | 78/96 (81.2%) | 78/90 | 0/6 | 0/5 | 155.0 |
| hase-resnet50-39 | 78/96 (81.2%) | 72/90 | 6/6 | 0/5 | 63.9 |

## live-held-2-frames

| Model | Exact | Non-red exact | Red exact | Complete frames | ms/crop |
| --- | ---: | ---: | ---: | ---: | ---: |
| cvmaj+automajsoul-red-gate | 28/28 (100.0%) | 26/26 | 2/2 | 2/2 | 1.6 |
| automajsoul-tilenet38 | 27/28 (96.4%) | 25/26 | 2/2 | 1/2 | 1.3 |
| cvmaj-cnn34 | 26/28 (92.9%) | 26/26 | 0/2 | 0/2 | 0.3 |
| local-cnn37 | 26/28 (92.9%) | 24/26 | 2/2 | 0/2 | 0.1 |
| current-template-face-lofo | 26/28 (92.9%) | 24/26 | 2/2 | 0/2 | — |
| hase-resnet50-39 | 24/28 (85.7%) | 22/26 | 2/2 | 0/2 | 61.2 |
| pjura-vit34 | 22/28 (78.6%) | 22/26 | 0/2 | 0/2 | 141.2 |

## pjura-public-holdout

| Model | Exact | Non-red exact | Red exact | Complete frames | ms/crop |
| --- | ---: | ---: | ---: | ---: | ---: |
| pjura-vit34 | 105/105 (100.0%) | 105/105 | — | — | 147.7 |
| hase-resnet50-39 | 86/105 (81.9%) | 86/105 | — | — | 62.1 |
| current-template-face-lofo | 73/105 (69.5%) | 73/105 | — | — | 98.3 |
| cvmaj-cnn34 | 66/105 (62.9%) | 66/105 | — | — | 0.1 |
| cvmaj+automajsoul-red-gate | 65/105 (61.9%) | 65/105 | — | — | 1.3 |
| automajsoul-tilenet38 | 59/105 (56.2%) | 59/105 | — | — | 1.2 |

## Limitations

- The live set contains only 96 crops from 7 correlated frames in one session and does not cover all 37 classes.
- The only observed red five is red sou; red man and red pin are absent.
- Six legacy crops labeled 2s were visually verified as 3s and corrected only in this comparison report; source training manifests were not changed.
- The public holdout comes from pjura/mahjong_souls_tiles and may overlap pjura ViT training or augmentation lineage.
- The local CNN is reported only on its two held source frames; the remaining live source frames were training data.
- HaseLab preprocessing is inferred from the declared timm/resnet50 architecture because the model card does not publish transforms.
- Latency is CPU batch throughput on this machine, not single-frame end-to-end screen recognition latency.
