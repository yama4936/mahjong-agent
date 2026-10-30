"""Offline closed-tsumo experiment; not connected to gameplay or decision making.

The caller asserts situational yaku are absent; this function cannot prove it.
Only supplied tiles are checked; unseen opponent hands and all-table physical
consistency are unknown. Deposits=0 models the hand award, not an actual
settlement with existing riichi sticks. baseYaku excludes extra north/ura han.
"""
import json
import sys
from collections import Counter
from mahjong.constants import EAST, SOUTH, WEST, NORTH, AKA_DORAS
from mahjong.hand_calculating.hand import HandCalculator
from mahjong.hand_calculating.hand_config import HandConfig, OptionalRules
from score_closed_waits import convert

SEATS = {"east": EAST, "south": SOUTH, "west": WEST}
WINDS = {**SEATS, "north": NORTH}
FIELDS = {"hand", "winner", "seat", "roundWind", "riichi", "indicators", "uraIndicators", "kita", "honba", "deposits", "pao", "melds", "tsumoLoss", "situationalYakuExcluded"}


def ordinary_basic_points(han, fu):
    if type(han) is not int or not 1 <= han <= 12 or type(fu) is not int or fu < 20:
        raise ValueError("Unsupported han or fu")
    if han >= 11: return 6000
    if han >= 8: return 4000
    if han >= 6: return 3000
    if han >= 5: return 2000
    return min(2000, fu * 2 ** (han + 2))


def score_sanma_closed_tsumo(data):
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise ValueError("Complete supported evidence is required")
    hand, indicators, ura = data["hand"], data["indicators"], data["uraIndicators"]
    if not isinstance(hand, list) or len(hand) != 14 or not all(isinstance(t, str) for t in hand):
        raise ValueError("Fourteen hand tiles are required")
    if data["seat"] not in SEATS or data["roundWind"] not in WINDS or type(data["riichi"]) is not bool:
        raise ValueError("Known winds and riichi status required")
    if type(data["kita"]) is not int or not 0 <= data["kita"] <= 4:
        raise ValueError("Invalid extracted north count")
    if type(data["honba"]) is not int or data["honba"] != 0 or type(data["deposits"]) is not int or data["deposits"] != 0 or data["pao"] is not False or data["melds"] != [] or data["tsumoLoss"] is not True or data["situationalYakuExcluded"] is not True:
        raise ValueError("Unsupported settlement or open hand")
    if not isinstance(indicators, list) or len(indicators) != 1 or not isinstance(ura, list):
        raise ValueError("Complete indicator evidence required")
    if (data["riichi"] and len(ura) != len(indicators)) or (not data["riichi"] and ura):
        raise ValueError("Complete ura indicator evidence required")
    all_tiles = hand + indicators + ura + ["N"] * data["kita"]
    if any(not isinstance(t, str) for t in all_tiles) or any(t in {"0m", "2m", "3m", "4m", "5m", "6m", "7m", "8m"} for t in all_tiles):
        raise ValueError("Impossible sanma tiles")
    if any(t in {"1m", "9m"} for t in indicators + ura):
        raise ValueError("Sanma manzu indicator cycle unsupported")
    counts = Counter("5" + t[1] if len(t) == 2 and t[0] == "0" else t for t in all_tiles)
    if any(n > 4 for n in counts.values()):
        raise ValueError("More than four physical copies")
    convert(all_tiles)  # Validate combined red/ordinary copy limits and tile names.
    if data["winner"] not in hand:
        raise ValueError("Winner tile missing")
    tiles = convert(hand)
    winner_type = convert([data["winner"]])[0] // 4
    winner = next(t for t in reversed(tiles) if t // 4 == winner_type
                  and ((t in AKA_DORAS) == data["winner"].startswith("0")))
    config = HandConfig(is_riichi=data["riichi"], is_tsumo=True, player_wind=SEATS[data["seat"]], round_wind=WINDS[data["roundWind"]], options=OptionalRules(has_open_tanyao=True, has_aka_dora=True, kiriage=False))
    result = HandCalculator.estimate_hand_value(tiles, winner, dora_indicators=convert(indicators), config=config)
    if result.error or not result.han or not result.fu or result.han >= 13:
        raise ValueError("Unsupported or invalid winning hand")
    yaku = [str(y) for y in result.yaku or []]
    if not any(not (name.startswith("Dora") or name.startswith("Aka Dora")) for name in yaku):
        raise ValueError("Dora alone is not a yaku")
    # Ura applies to concealed tiles and extracted north. Four-player scorer
    # already counted hand red and regular dora, but not extracted north.
    def next_honor(t):
        cycle = ["E", "S", "W", "N"] if t in ["E", "S", "W", "N"] else ["P", "F", "C"]
        return cycle[(cycle.index(t) + 1) % len(cycle)]
    def dora(t):
        if t.startswith("0"): t = "5" + t[1]
        return next_honor(t) if t in ["E", "S", "W", "N", "P", "F", "C"] else f"{int(t[0]) % 9 + 1}{t[1]}"
    extra = data["kita"] * (1 + sum(dora(t) == "N" for t in indicators + ura))
    extra += sum(sum(("5" + t[1] if t.startswith("0") else t) == dora(indicator) for t in hand) for indicator in ura)
    han = result.han + extra
    if han >= 13:
        raise ValueError("Counted yakuman unsupported")
    basic = ordinary_basic_points(han, result.fu)
    return {"scope": "experimental_sanma_closed_tsumo", "baseHan": result.han, "extraHan": extra, "han": han, "fu": result.fu, "basicPoints": basic, "seat": data["seat"], "baseYaku": yaku}

if __name__ == "__main__":
    print(json.dumps(score_sanma_closed_tsumo(json.load(sys.stdin))))
