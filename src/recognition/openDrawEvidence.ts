import { readdir } from "node:fs/promises";
import { loadTemplates, matchTile, type TileMatch } from "./templateMatcher.js";
import type { Rect } from "./layout.js";

export interface SelectedTileRecognition extends TileMatch {
  index: number;
  normalizedConsensus?: TileMatch;
}

/** A cached concealed row may accompany just one newly recognized draw. */
export function selectedTileRecognition(
  recognition: { tiles: unknown[]; matches: TileMatch[] }, index: number,
): SelectedTileRecognition | undefined {
  const match = recognition.matches.length === recognition.tiles.length
    ? recognition.matches[index]
    : recognition.matches.length === 1 && index === recognition.tiles.length - 1
      ? recognition.matches[0] : undefined;
  if (!match || match.tile !== recognition.tiles[index]) return undefined;
  return { ...match, index };
}

/** Strong agreement on a distinct but low-similarity raw face, never a relabel. */
export async function confirmWeakOpenDraw(
  selected: SelectedTileRecognition, verify: () => Promise<TileMatch>,
): Promise<SelectedTileRecognition> {
  const margin = selected.confidence - selected.runnerUpConfidence;
  if (selected.confidence >= 0.8 || selected.confidence < 0.7 || margin < 0.1) return selected;
  const confirmation = await verify();
  if (confirmation.tile !== selected.tile || confirmation.confidence < 0.95
    || confirmation.confidence - confirmation.runnerUpConfidence < 0.15) return selected;
  return { ...selected, normalizedConsensus: confirmation };
}

/** Keep augmented variants out of this independent normalized reference bank. */
export async function createOpenDrawVerifier(directory: string): Promise<
  ((screenshot: string | Buffer, rect: Rect) => Promise<TileMatch>) | undefined
> {
  const include = (file: string) => /__hf_(?:base|real_\d+)\.(?:png|jpe?g|webp)$/i.test(file);
  const files = (await readdir(directory)).filter(include);
  if (new Set(files.map(file => file.split("__")[0])).size < 34) return undefined;
  const options = { normalizeFace: true, allClasses: true, rejectBlank: true };
  const templates = await loadTemplates(directory, include, options);
  return (screenshot, rect) => matchTile(screenshot, rect, templates, options);
}
