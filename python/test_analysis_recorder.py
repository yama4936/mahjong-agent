import csv
import json
import tempfile
import unittest
from pathlib import Path
from analysis_recorder import AnalysisRecorder


class AnalysisRecorderTests(unittest.TestCase):
    def test_completed_only_and_duplicate_preserves_decisions(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = AnalysisRecorder(folder, 'friend-300-test')
            decision = {'timestamp':'2026-10-27T00:00:00Z','event':'decision','evaluation':{'state':{'round':'east_1','honba':0,'scores':[25000]*4,'hand':['1m']},'decision':{'selectedAction':{'action':'discard','tile':'1m'},'candidates':[{'score':0.4}]}},'execution':{'clicked':True}}
            recorder.observe(decision)
            self.assertEqual(list(Path(folder).glob('*/events.jsonl')), [])
            final = {'event':'outcome_observed','kind':'match','evidence':{'screenshot':'/frames/match.png'}}
            recorder.observe(final)
            path = next(Path(folder).glob('*/events.jsonl'))
            before = path.read_bytes()
            rows = [json.loads(line) for line in before.splitlines()]
            self.assertIsNone(rows[0]['confirmedResult'])
            self.assertEqual(rows[0]['state']['scores'], [25000]*4)
            with path.with_name('decisions.csv').open(encoding='utf-8-sig') as f:
                csv_rows = list(csv.DictReader(f))
            self.assertEqual(csv_rows[0]['tile'], '1m')
            self.assertEqual(csv_rows[0]['matchId'], rows[0]['matchId'])
            recorder.observe(final)
            recorder.observe(decision)  # unfinished successor is not exported
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(list(Path(folder).glob('*/events.jsonl'))), 1)

    def test_round_index_and_missing_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = AnalysisRecorder(folder, 'run')
            recorder.observe({'event':'outcome_observed','kind':'round'})
            recorder.observe({'event':'reaction_win','execution':{'action':'ron','clicked':True}})
            recorder.observe({'event':'outcome_observed','kind':'match'})
            self.assertEqual(list(Path(folder).glob('*/events.jsonl')), [])
            rows = [json.loads(line) for line in recorder.pending.read_text().splitlines()]
            self.assertEqual(rows[1]['roundIndex'], 1)
            self.assertIsNone(rows[1]['state'])

if __name__ == '__main__':
    unittest.main()
