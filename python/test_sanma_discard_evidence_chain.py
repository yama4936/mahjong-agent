"""Retained run 123: evidence correlation, deliberately no action authority."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from sanma_discard_evidence_chain import evaluate

ROOT = Path(__file__).resolve().parents[1] / 'test/fixtures/sanma-evidence-chain-123'


class DiscardEvidenceChainTest(unittest.TestCase):
    def setUp(self):
        self.before, self.first, self.second = [ROOT / f'{i}.json' for i in range(3)]
        self.journal = json.loads((ROOT/'journal.json').read_text())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def altered(self, path, mutate):
        doc = json.loads(path.read_text())
        screenshot = Path(doc['screenshot'])
        if not screenshot.is_absolute():
            doc['screenshot'] = str((path.parent / screenshot).resolve())
        mutate(doc)
        result = Path(self.tmp.name) / 'changed.json'
        result.write_text(json.dumps(doc))
        return result

    def assert_pending(self, before=None, after=None, journal=None):
        result = evaluate(before or self.before, after or [self.first, self.second],
                          self.journal if journal is None else journal)
        self.assertEqual(result['state'], 'pending', result)
        self.assertFalse(result['operationAuthorized'])
        self.assertFalse(result['confirmed'])

    def test_observed_chain_stays_unconfirmed_candidate(self):
        result = evaluate(self.before, [self.first, self.second], self.journal)
        self.assertEqual(result['state'], 'later_turn_evidence_candidate', result)
        self.assertFalse(result['operationAuthorized'])
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['evidence']['remainingCandidates'], [50, 47, 47])
        self.assertEqual(result['evidence']['selectedTile'], '1m')

    def test_missing_selection_and_spliced_journal_fail(self):
        self.assert_pending(journal=self.journal[:1])
        journal = copy.deepcopy(self.journal)
        journal[1]['clickIndex'] = 13
        self.assert_pending(journal=journal)
        journal = copy.deepcopy(self.journal)
        journal[1]['status'] = 'failed'
        self.assert_pending(journal=journal)

    def test_reused_reordered_or_early_images_fail(self):
        self.assert_pending(after=[self.first, self.first])
        self.assert_pending(after=[self.second, self.first])
        journal = copy.deepcopy(self.journal)
        journal[1]['timestamp'] = '2026-11-03T08:27:00+00:00'
        self.assert_pending(journal=journal)

    def test_round_seat_count_and_draw_mismatch_fail(self):
        for field, value in [('round', 'east_2'), ('seat', 'east'), ('remainingTiles', 50)]:
            path = self.altered(self.second, lambda x: x['sourceObservation']['board']['candidate'].__setitem__(field, value))
            self.assert_pending(after=[self.first, path])
        path = self.altered(self.second, lambda x: x['drawCandidate'].__setitem__('tile', '1m'))
        self.assert_pending(after=[self.first, path])

    def test_wrong_selected_tile_or_missing_label_fails(self):
        journal = copy.deepcopy(self.journal)
        for event in journal:
            event['tile'] = '9m'
        self.assert_pending(journal=journal)
        path = self.altered(self.second, lambda x: x['sourceObservation']['ownRiver']['candidates'].clear())
        self.assert_pending(after=[self.first, path])

    def test_wrong_index_rejected_even_when_journal_entries_agree(self):
        journal = copy.deepcopy(self.journal)
        for event in journal:
            event['clickIndex'] = 13
        self.assert_pending(journal=journal)
        for event in journal:
            event['clickPoint'] = {'x': 1532, 'y': 996.5}
        self.assert_pending(journal=journal)

    def test_wrong_frame_binding_fails(self):
        path = self.altered(self.second, lambda x: x.__setitem__('digest', '0'*64))
        self.assert_pending(after=[self.first, path])


if __name__ == '__main__':
    unittest.main()
