/** Payment calculation only; no yaku/fu/han, honba, deposits or pao. */
type Seat = "east" | "south" | "west";
type Common = { basicPoints: number; winner: Seat; tsumoLoss: true };
export type SanmaPaymentInput = Common & (
  | { method: "ron"; discarder: Seat }
  | { method: "tsumo" }
);
export type SanmaPayments = Record<Seat, number>;

const seats: readonly Seat[] = ["east", "south", "west"];

/**
 * Point changes for one sanma win with tsumo loss and no other transfers.
 * East is the dealer. basicPoints must already include all limits/yakuman.
 * Explicitly reject extra properties to avoid silently dropping honba,
 * riichi deposits, pao or other settlement information.
 * This helper does not enable sanma decisions or gameplay.
 */
export function calculateSanmaPayments(input: SanmaPaymentInput): SanmaPayments {
  if (!input || typeof input !== "object") throw new Error("Invalid payment input");
  const allowed = new Set(["basicPoints", "winner", "tsumoLoss", "method", "discarder"]);
  if (Object.keys(input).some(key => !allowed.has(key))) throw new Error("Unsupported payment adjustment");
  if (input.tsumoLoss !== true) throw new Error("Only tsumo-loss rules are supported");
  if (!Number.isSafeInteger(input.basicPoints) || input.basicPoints <= 0 || input.basicPoints > Math.floor((Number.MAX_SAFE_INTEGER - 99) / 6)) {
    throw new Error("Invalid basic points");
  }
  if (!seats.includes(input.winner)) throw new Error("Invalid winner seat");
  if (input.method !== "ron" && input.method !== "tsumo") throw new Error("Invalid win method");
  if (input.method === "ron" && (!seats.includes(input.discarder) || input.discarder === input.winner)) {
    throw new Error("Invalid discarder");
  }
  if (input.method === "tsumo" && Object.hasOwn(input, "discarder")) throw new Error("Tsumo has no discarder");
  const delta: SanmaPayments = { east: 0, south: 0, west: 0 };
  const rounded = (multiplier: number) => Math.ceil(input.basicPoints * multiplier / 100) * 100;
  for (const payer of seats) {
    if (payer === input.winner || (input.method === "ron" && payer !== input.discarder)) continue;
    const multiplier = input.method === "ron" ? (input.winner === "east" ? 6 : 4)
      : input.winner === "east" || payer === "east" ? 2 : 1;
    const payment = rounded(multiplier);
    delta[payer] -= payment;
    delta[input.winner] += payment;
  }
  return delta;
}
