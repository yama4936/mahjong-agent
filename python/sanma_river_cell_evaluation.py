"""Count diagnostic outcomes on named, hand-reviewed image pairs only.

Pairs from one recording are correlated; these tiny counts do not estimate a
population error rate. This evaluates pixel occupancy, not actual gameplay.
"""
import json
from pathlib import Path
from sanma_river_cell_diagnostic import compare

ROOT = Path(__file__).resolve().parents[1] / 'test/fixtures/sanma-discard-trajectory-122'


def evaluate(cases=None):
    if cases is None:
        cases = [
            ('south immediate', ROOT/'before.png', ROOT/'after.png', True, 'run122'),
            ('south next turn', ROOT/'before.png', ROOT/'next_turn.png', True, 'run122'),
            ('pon', ROOT/'pon_before.png', ROOT/'pon_after.png', False, 'independent-pon'),
            ('same image', ROOT/'before.png', ROOT/'before.png', False, 'run122'),
            ('existing tile', ROOT/'after.png', ROOT/'next_turn.png', False, 'run122'),
        ]
    counts = {'truePositive': 0, 'falsePositive': 0, 'trueNegative': 0, 'falseNegative': 0}
    results = []
    for name, before, after, expected, source in cases:
        if type(expected) is not bool:
            raise ValueError('expected must be a reviewed boolean label')
        result = compare(before, after)
        observed = result['singlePhysicalAppendCandidate']
        key = ('truePositive' if observed else 'falseNegative') if expected else ('falsePositive' if observed else 'trueNegative')
        counts[key] += 1
        results.append({'case': name, 'source': source, 'expected': expected, 'observed': observed,
                        'beforeSha256': result['beforeSha256'], 'afterSha256': result['afterSha256']})
    return {'scope': 'offline_untrusted_physical_river_evaluation', 'confirmed': False,
            'operationAuthorized': False, 'counts': counts, 'cases': results,
            'limitations': ['manual labels, not gameplay confirmation', 'pairs sharing a source are correlated',
                            'small convenience sample, no population error rates or operational calibration']}


if __name__ == '__main__':
    print(json.dumps(evaluate(), indent=2))
