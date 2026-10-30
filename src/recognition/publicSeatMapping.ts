/** Pure position mapping. This does not recognize or certify screen regions. */
type Seat = "east" | "south" | "west" | "north";
type Position = "right" | "opposite" | "left";
type Rules = "yonma" | "sanma";

/**
 * Convert explicitly supplied opponent screen-position values into seats.
 * Rules default to yonma. Sanma requires both real positions and rejects
 * any right property, including undefined. The caller must establish game
 * type and own seat independently; no live recognizer uses this helper.
 */
export function mapPublicOpponentPositions<T>(ownSeat: Seat,
  positions: Partial<Record<Position, T>>, rules: Rules = "yonma"): Partial<Record<Seat, T>> {
  const seats: readonly Seat[] = rules === "sanma" ? ["east", "south", "west"]
    : rules === "yonma" ? ["east", "south", "west", "north"] : [];
  const own = seats.indexOf(ownSeat);
  if (own < 0) throw new Error("Invalid own seat or rules");
  if (!positions || typeof positions !== "object" || Array.isArray(positions)) throw new Error("Invalid positions");
  const keys = Object.keys(positions);
  if (keys.some(key => !["right", "opposite", "left"].includes(key))) throw new Error("Invalid position");
  if (rules === "sanma" && Object.hasOwn(positions, "right")) throw new Error("Sanma has no right seat");
  const required: Position[] = rules === "sanma" ? ["opposite", "left"] : ["right", "opposite", "left"];
  if (required.some(key => !Object.hasOwn(positions, key) || positions[key] === undefined)) throw new Error("Missing position");
  const result: Partial<Record<Seat, T>> = {};
  for (const position of required) {
    const offset = rules === "sanma" ? (position === "opposite" ? 1 : 2)
      : position === "right" ? 1 : position === "opposite" ? 2 : 3;
    result[seats[(own + offset) % seats.length]!] = positions[position]!;
  }
  return result;
}
