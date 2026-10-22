import copy
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock
from auto_operator import PythonAutoOperator


class QueuedDiscardReceiptTest(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).resolve().parents[1]
            / 'test/fixtures/queued-own-discard-20261022.json').read_text())
        self.baseline = self.fixture['receipts'][0]['before']
        self.op = PythonAutoOperator.__new__(PythonAutoOperator)
        self.op.pending_own_discard = None
        self.op.pending_own_river_confirmation = None
        self.op.public_recognition_lock = threading.Lock()
        self.op.public_cache_generation = 8
        self.op.cached_open_melds = 1
        self.op.cached_public_observation = {'ownDiscards': list(self.baseline)}
        self.op.previous_public_observation = None
        self.op.cached_concealed_tiles = ['1p'] * 10
        self.op.log = Mock()
        self.op.record_post_riichi_pass_candidate = Mock()
        for receipt in self.fixture['receipts']:
            self.op.register_pending_own_discard(copy.deepcopy(receipt))

    def scan(self, river, at):
        self.op.public_recognition_result = {'generation': 8, 'result': {
            'ownDiscards': list(river), 'capturedAt': at}}
        self.op.poll_public_recognition()
        self.op.reconcile_own_discard()

    def test_original_white_eight_sequence_needs_both_independent_scans(self):
        first, second = self.fixture['scans']
        self.scan(first['ownDiscards'], first['capturedAt'])
        self.assertIsNotNone(self.op.pending_own_discard)
        self.assertEqual(self.op.cached_public_observation['ownDiscards'], self.baseline)
        self.scan(second['ownDiscards'], second['capturedAt'])
        self.assertIsNone(self.op.pending_own_discard)
        reconciled = [c.kwargs['tile'] for c in self.op.log.call_args_list
                      if c.args[0] == 'own_discard_reconciled']
        self.assertEqual(reconciled, ['P', '8s'])
        contexts = self.op.record_post_riichi_pass_candidate.call_args_list
        self.assertEqual(contexts[0].args[0]['before'], self.baseline)
        self.assertEqual(contexts[1].args[0]['before'], self.baseline + ['P'])

    def test_partial_prefix_keeps_latest_receipt_pending(self):
        for stamp in ['2026-10-22T04:10:50+00:00', '2026-10-22T04:10:51+00:00']:
            self.scan(self.baseline + ['P'], stamp)
        self.assertEqual(self.op.pending_own_discard['tile'], '8s')
        self.assertEqual(self.op.pending_own_discard['before'], self.baseline + ['P'])
        for stamp in ['2026-10-22T04:10:52+00:00', '2026-10-22T04:10:53+00:00']:
            self.scan(self.baseline + ['P', '8s'], stamp)
        self.assertIsNone(self.op.pending_own_discard)

    def test_wrong_order_or_identity_quarantines_untrusted_river(self):
        for tail in [['8s', 'P'], ['F', '8s']]:
            with self.subTest(tail=tail):
                self.setUp()
                for stamp in ['2026-10-22T04:10:52+00:00', '2026-10-22T04:10:53+00:00']:
                    self.scan(self.baseline + tail, stamp)
                self.assertIsNone(self.op.pending_own_discard)
                self.assertIsNone(self.op.cached_concealed_tiles)
                self.assertEqual(self.op.cached_public_observation['ownDiscards'], self.baseline)
                self.assertTrue(any(c.args[0] == 'own_discard_mismatch' for c in self.op.log.call_args_list))

    def test_extra_automatic_discard_is_not_certified_by_receipts(self):
        for stamp in ['2026-10-22T04:10:52+00:00', '2026-10-22T04:10:53+00:00']:
            self.scan(self.baseline + ['P', '8s', '4m'], stamp)
        self.assertIsNone(self.op.pending_own_discard)
        self.assertIsNone(self.op.cached_concealed_tiles)
        self.assertTrue(any(c.args[0] == 'own_discard_reconciliation_failed' for c in self.op.log.call_args_list))

    def test_wrong_generation_cannot_confirm_queued_receipts(self):
        self.op.public_recognition_result = {'generation': 7, 'result': self.fixture['scans'][1]}
        self.op.poll_public_recognition()
        self.op.reconcile_own_discard()
        self.assertIsNotNone(self.op.pending_own_discard)
        self.assertEqual(self.op.cached_public_observation['ownDiscards'], self.baseline)

    def test_disappearing_sequence_candidate_is_unresolved_not_confirmed(self):
        self.scan(self.baseline + ['P', '8s'], '2026-10-22T04:10:50+00:00')
        self.scan(self.baseline, '2026-10-22T04:10:51+00:00')
        self.assertIsNotNone(self.op.pending_own_discard)
        self.scan(self.baseline, '2026-10-22T04:10:52+00:00')
        self.assertIsNone(self.op.pending_own_discard)
        self.assertIsNone(self.op.cached_concealed_tiles)
        self.assertTrue(any(c.args[0] == 'own_discard_reconciliation_unresolved' for c in self.op.log.call_args_list))
        self.assertFalse(any(c.args[0] == 'own_discard_reconciled' for c in self.op.log.call_args_list))

    def test_older_baseline_is_not_reused_after_independent_prefix_advances(self):
        previous = self.op.pending_own_discard
        fresh = {'tile': '4m', 'before': self.baseline + ['P', '8s']}
        self.op.register_pending_own_discard(fresh)
        self.assertIs(self.op.pending_own_discard, fresh)
        self.assertNotIn('earlierReceipts', fresh)
        self.assertIsNone(self.op.cached_concealed_tiles)
        self.assertTrue(any(c.args[0] == 'own_discard_reconciliation_unresolved' for c in self.op.log.call_args_list))

    def test_native_called_away_prefix_is_unresolved_without_certifying_a_call(self):
        fixture = json.loads((Path(__file__).resolve().parents[1]
            / 'test/fixtures/queued-called-away-discard-20261022.json').read_text())
        self.baseline = fixture['receipts'][0]['before']
        self.op.pending_own_discard = None
        self.op.cached_public_observation = {'ownDiscards': list(self.baseline)}
        self.op.log.reset_mock()
        for receipt in fixture['receipts']:
            self.op.register_pending_own_discard(copy.deepcopy(receipt))
        self.scan(fixture['scans'][0]['ownDiscards'], fixture['scans'][0]['capturedAt'])
        self.assertIsNotNone(self.op.pending_own_discard)
        self.assertFalse(any(c.args[0] == 'own_discard_reconciliation_unresolved'
                             for c in self.op.log.call_args_list))
        self.scan(fixture['scans'][1]['ownDiscards'], fixture['scans'][1]['capturedAt'])
        self.assertIsNone(self.op.pending_own_discard)
        self.assertIsNone(self.op.cached_concealed_tiles)
        self.assertEqual(self.op.cached_public_observation['ownDiscards'], self.baseline)
        unresolved = [c for c in self.op.log.call_args_list
                      if c.args[0] == 'own_discard_reconciliation_unresolved']
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].kwargs['reason'], 'river_missing_queued_receipt')
        self.assertEqual(unresolved[0].kwargs['receiptTiles'], ['5m', '6m'])
        self.assertFalse(any(c.args[0] in {'own_discard_mismatch', 'own_discard_reconciled'}
                             for c in self.op.log.call_args_list))
        self.op.record_post_riichi_pass_candidate.assert_not_called()
        # With the ambiguous queue retired, a later independent scan may
        # establish the real river without tying it to a requested click.
        self.scan(fixture['scans'][1]['ownDiscards'], '2026-10-22T05:45:03+00:00')
        self.assertEqual(self.op.cached_public_observation['ownDiscards'], ['9s', '6m'])

    def test_missing_interior_or_duplicate_receipt_never_certifies_a_sparse_sequence(self):
        for expected, observed in [(['P', '4m', '8s'], ['P', '8s']),
                                   (['P', 'P', '8s'], ['P', '8s']),
                                   (['P', '8s'], ['8s'])]:
            with self.subTest(expected=expected, observed=observed):
                self.setUp()
                self.op.pending_own_discard = None
                self.op.log.reset_mock()
                for tile in expected:
                    self.op.register_pending_own_discard({'tile': tile, 'before': list(self.baseline)})
                for stamp in ['2026-10-22T04:10:52+00:00', '2026-10-22T04:10:53+00:00']:
                    self.scan(self.baseline + observed, stamp)
                self.assertIsNone(self.op.pending_own_discard)
                self.assertIsNone(self.op.cached_concealed_tiles)
                self.assertEqual(self.op.cached_public_observation['ownDiscards'], self.baseline)
                self.assertTrue(any(c.args[0] == 'own_discard_reconciliation_unresolved'
                                    for c in self.op.log.call_args_list))
                self.assertFalse(any(c.args[0] in {'own_discard_mismatch', 'own_discard_reconciled'}
                                     for c in self.op.log.call_args_list))
                self.op.record_post_riichi_pass_candidate.assert_not_called()

    def test_shorter_wrong_identity_or_reversed_order_still_mismatches(self):
        for observed in [['F'], ['8s', 'P']]:
            with self.subTest(observed=observed):
                self.setUp()
                self.op.pending_own_discard = None
                self.op.log.reset_mock()
                for tile in ['P', '4m', '8s']:
                    self.op.register_pending_own_discard({'tile': tile, 'before': list(self.baseline)})
                for stamp in ['2026-10-22T04:10:52+00:00', '2026-10-22T04:10:53+00:00']:
                    self.scan(self.baseline + observed, stamp)
                self.assertIsNone(self.op.pending_own_discard)
                self.assertIsNone(self.op.cached_concealed_tiles)
                self.assertEqual(self.op.cached_public_observation['ownDiscards'], self.baseline)
                self.assertTrue(any(c.args[0] == 'own_discard_mismatch'
                                    for c in self.op.log.call_args_list))
                self.assertFalse(any(c.args[0] in {'own_discard_reconciliation_unresolved',
                                                  'own_discard_reconciled'}
                                     for c in self.op.log.call_args_list))

    def test_native_called_first_copy_cannot_take_credit_for_later_identical_discard(self):
        fixture = json.loads((Path(__file__).resolve().parents[1]
            / 'test/fixtures/called-identical-discard-20261022.json').read_text())
        self.baseline = fixture['receipts'][0]['before']
        self.op.pending_own_discard = None
        self.op.cached_public_observation = {'ownDiscards': list(self.baseline)}
        self.op.log.reset_mock()
        for original in fixture['receipts']:
            receipt = copy.deepcopy(original)
            receipt['opponentMeldsBefore'] = self.op.own_discard_meld_snapshot(
                {'state': {'opponents': receipt.pop('sourceOpponents')}})
            self.op.register_pending_own_discard(receipt)
        self.assertNotIn('earlierReceipts', self.op.pending_own_discard)
        self.assertIsNone(self.op.cached_concealed_tiles)
        unresolved = [c for c in self.op.log.call_args_list
                      if c.args[0] == 'own_discard_reconciliation_unresolved']
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].kwargs['reason'], 'new_meld_may_contain_pending_discard')
        for scan in fixture['scans']:
            self.scan(scan['ownDiscards'], scan['capturedAt'])
        self.assertIsNone(self.op.pending_own_discard)
        verified = self.op.record_post_riichi_pass_candidate.call_args_list
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0].args[0]['clickedAt'], fixture['receipts'][1]['clickedAt'])
        self.assertFalse(any(c.args[0] == 'own_discard_mismatch' for c in self.op.log.call_args_list))

    def test_only_a_new_observed_callable_meld_can_retire_an_older_receipt(self):
        old = {'east': []}
        chi = {'type': 'chi', 'tiles': ['3m', '4m', '0m']}
        for before, after in [(old, {'east': [chi]}),
                              ({'east': [chi]}, {'east': [chi]}),
                              ({}, {'east': [chi]}),
                              (old, {'east': [{'type': 'ankan', 'tiles': ['3m'] * 4}]}),
                              (old, {'east': [{'type': 'pon', 'tiles': ['5m'] * 3}]})]:
            with self.subTest(before=before, after=after):
                self.op.pending_own_discard = None
                self.op.log.reset_mock()
                self.op.register_pending_own_discard({'tile': '3m', 'before': self.baseline,
                    'opponentMeldsBefore': before})
                self.op.register_pending_own_discard({'tile': '6m', 'before': self.baseline,
                    'opponentMeldsBefore': after})
                called = before == old and after == {'east': [chi]}
                self.assertEqual('earlierReceipts' in self.op.pending_own_discard, not called)
        snapshot = self.op.own_discard_meld_snapshot({'state': {'opponents': [
            {'seat': 'east', 'openMelds': 1, 'openMeldsObserved': False, 'melds': [chi]},
            {'seat': 'south', 'openMelds': 2, 'openMeldsObserved': True, 'melds': [chi]},
            {'seat': 'west', 'openMelds': 1, 'openMeldsObserved': True, 'melds': [chi]},
        ]}})
        self.assertEqual(snapshot, {'west': [chi]})

    def test_partial_identical_receipts_are_ambiguous_even_without_observed_melds(self):
        for expected, observed in [(['P', 'P', '8s'], ['P']),
                                   (['P', '8s', 'P'], ['P']),
                                   (['P', '8s', '8s'], ['P', '8s'])]:
            with self.subTest(expected=expected, observed=observed):
                self.setUp()
                self.op.pending_own_discard = None
                self.op.log.reset_mock()
                for tile in expected:
                    self.op.register_pending_own_discard({'tile': tile, 'before': list(self.baseline)})
                for stamp in ['2026-10-22T04:10:52+00:00', '2026-10-22T04:10:53+00:00']:
                    self.scan(self.baseline + observed, stamp)
                self.assertIsNone(self.op.pending_own_discard)
                self.assertIsNone(self.op.cached_concealed_tiles)
                self.assertEqual(self.op.cached_public_observation['ownDiscards'], self.baseline)
                unresolved = [c for c in self.op.log.call_args_list
                              if c.args[0] == 'own_discard_reconciliation_unresolved']
                self.assertEqual(len(unresolved), 1)
                self.assertEqual(unresolved[0].kwargs['reason'], 'ambiguous_identical_receipt_prefix')
                self.op.record_post_riichi_pass_candidate.assert_not_called()

    def test_later_duplicate_does_not_make_a_unique_full_prefix_ambiguous(self):
        self.op.pending_own_discard = None
        self.op.log.reset_mock()
        for tile in ['P', '8s', 'P']:
            self.op.register_pending_own_discard({'tile': tile, 'before': list(self.baseline)})
        for stamp in ['2026-10-22T04:10:52+00:00', '2026-10-22T04:10:53+00:00']:
            self.scan(self.baseline + ['P', '8s'], stamp)
        self.assertIsNotNone(self.op.pending_own_discard)
        self.assertEqual(self.op.pending_own_discard['before'], self.baseline + ['P', '8s'])
        verified = [c.kwargs['tile'] for c in self.op.log.call_args_list
                    if c.args[0] == 'own_discard_reconciled']
        self.assertEqual(verified, ['P', '8s'])
        self.assertFalse(any(c.args[0] == 'own_discard_reconciliation_unresolved'
                             for c in self.op.log.call_args_list))
