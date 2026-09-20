# Bootstrap tile templates

`bootstrap/` is generated from `pjura/mahjong_souls_tiles`, an Apache-2.0 dataset containing tile crops from Mahjong Soul.

- Source: https://huggingface.co/datasets/pjura/mahjong_souls_tiles
- Pinned revision: `8c0f22e7c6b64be55bb1d2767fe1a63981788de7`
- License declared by dataset author: Apache-2.0

Run `npm run templates:fetch` to reproduce the base image and twenty fixed augmentation variants for each of the 34 classes, plus the dataset's available real screenshot crops. These are bootstrap images; collect templates from the actual configured client for production confidence calibration.
