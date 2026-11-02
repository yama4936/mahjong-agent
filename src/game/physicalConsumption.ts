import { normalizeTile, type GameTile, type Tile } from "./tiles.js";

/** Preserve forced physical tiles; expose red/normal alternatives without
 * pretending the UI confirmed which copy it consumed. Structural action IDs
 * remain unchanged, including the order of the chi selectors. */
export function physicalConsumption(hand: readonly GameTile[], required: readonly Tile[]) {
  const choices = new Map<string, GameTile[]>();
  function visit(remaining: GameTile[], selected: GameTile[]): void {
    if (selected.length === required.length) {
      const key = [...selected].sort().join("_");
      if (!choices.has(key)) choices.set(key, selected);
      return;
    }
    const tried = new Set<GameTile>();
    remaining.forEach((tile, index) => {
      if (normalizeTile(tile) !== required[selected.length] || tried.has(tile)) return;
      tried.add(tile);
      visit([...remaining.slice(0, index), ...remaining.slice(index + 1)], [...selected, tile]);
    });
  }
  visit([...hand], []);
  const alternatives = [...choices.values()];
  if (!alternatives.length) throw new Error("Call consumption is not present in concealed hand");
  return { consumedTiles: alternatives[0]!,
    ...(alternatives.length > 1 ? { consumedTileChoices: alternatives } : {}) };
}

