"""Offline closed-hand scoring, not a prediction of win probability or policy EV."""
import argparse
import json
import sys
from collections import Counter
from importlib.metadata import version
from mahjong.constants import EAST, SOUTH, WEST, NORTH
from mahjong.hand_calculating.hand import HandCalculator
from mahjong.hand_calculating.hand_config import HandConfig, OptionalRules
from mahjong.tile import TilesConverter

WINDS = {"east": EAST, "south": SOUTH, "west": WEST, "north": NORTH}
HONORS = {"E": "1", "S": "2", "W": "3", "N": "4", "P": "5", "F": "6", "C": "7"}


def convert(tiles):
    counts = Counter(("5" + tile[1]) if tile.startswith("0") else tile for tile in tiles)
    if any(count > 4 for count in counts.values()):
        raise ValueError("Impossible tile multiplicity")
    for suit in "mps":
        if tiles.count("0" + suit) > 1 or tiles.count("5" + suit) > 3:
            raise ValueError("Impossible red/normal five multiplicity with aka dora enabled")
    suits = {"m": "", "p": "", "s": "", "z": ""}
    for tile in tiles:
        if tile in HONORS:
            suits["z"] += HONORS[tile]
        elif len(tile) == 2 and tile[0] in "0123456789" and tile[1] in "mps":
            suits[tile[1]] += tile[0]
        else:
            raise ValueError(f"Unsupported tile: {tile}")
    result = TilesConverter.string_to_136_array(man=suits["m"], pin=suits["p"], sou=suits["s"], honors=suits["z"], has_aka_dora=True)
    if len(set(result)) != len(result) or any(not 0 <= tile < 136 for tile in result):
        raise ValueError("Impossible tile multiplicity")
    return result


def score_scenarios(state, cost, tsumo):
    """Immediate four-player score changes, never final-placement predictions."""
    scores = state.get("scores", {})
    if set(scores) != set(WINDS):
        return []
    if any(isinstance(value, bool) or not isinstance(value, int) for value in scores.values()):
        raise ValueError("Integer four-player scores required")
    winner = state["seat"]
    payers = [seat for seat in WINDS if seat != winner]
    cases = [None] if tsumo else payers
    scenarios = []
    for payer in cases:
        after = dict(scores)
        if tsumo:
            for seat in payers:
                payment = cost["main"] if winner == "east" or seat == "east" else cost["additional"]
                after[seat] -= payment
                after[winner] += payment
        else:
            after[payer] -= cost["main"]
            after[winner] += cost["main"]
        best_rank = 1 + sum(value > after[winner] for seat, value in after.items() if seat != winner)
        worst_rank = best_rank + sum(value == after[winner] for seat, value in after.items() if seat != winner)
        scenarios.append({"payer": payer, "scores": after, "rankRange": [best_rank, worst_rank],
            "scope": "immediate_scores_not_final_match_rank", "dealer_win": winner == "east"})
    return scenarios


def score_waits(state, discard, waits):
    if state.get("openMelds", 0) or state.get("melds"):
        raise ValueError("This verifier supports closed hands without melds only")
    if state.get("riichiDeclared"):
        raise ValueError("Cannot compare dama after a declared riichi")
    round_wind = state.get("round", "").split("_")[0]
    if state.get("seat") not in WINDS or round_wind not in WINDS:
        raise ValueError("Known seat and round wind required")
    concealed = list(state["hand"]) + ([state["draw"]] if state.get("draw") else [])
    concealed.remove(discard)
    if len(concealed) != 13:
        raise ValueError("Expected thirteen tiles after discard")
    rows = []
    for wait in waits:
        tiles = convert(concealed + [wait])
        winner_type = convert([wait])[0] // 4
        winner = next(tile for tile in reversed(tiles) if tile // 4 == winner_type)
        for riichi in (False, True):
            for tsumo in (False, True):
                config = HandConfig(is_riichi=riichi, is_tsumo=tsumo,
                    player_wind=WINDS[state["seat"]], round_wind=WINDS[round_wind],
                    options=OptionalRules(has_open_tanyao=True, has_aka_dora=True, kiriage=False))
                result = HandCalculator.estimate_hand_value(tiles, winner,
                    dora_indicators=convert(state.get("doraIndicators", [])), config=config)
                rows.append({"wait": wait, "riichi": riichi, "tsumo": tsumo,
                    "error": result.error, "han": result.han, "fu": result.fu,
                    "yaku": [str(yaku) for yaku in result.yaku or []], "cost": result.cost,
                    "scoreScenarios": score_scenarios(state, result.cost, tsumo) if result.cost else []})
    return {"library": f"mahjong=={version('mahjong')}", "discard": discard,
        "scope": "closed_hand_scoring_not_policy_ev",
        "assumptions": {"ippatsu": False, "ura_dora": False, "last_tile_bonus": False,
            "honba_and_deposits_excluded": True, "furiten_not_checked": True,
            "riichi_self_deposit_return_cancels_on_own_win": True}, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("replay")
    parser.add_argument("--discard", required=True)
    parser.add_argument("--wait", action="append", required=True)
    args = parser.parse_args()
    if args.replay == "-":
        replay = json.load(sys.stdin)
    else:
        with open(args.replay, encoding="utf-8") as source:
            replay = json.load(source)
    print(json.dumps(score_waits(replay["state"], args.discard, args.wait), ensure_ascii=False, indent=2))
