"""Versioned analysis exports. Only completed matches are published.

Values from evaluation are observations/estimates, never certified game results.
Pending data lives in a private staging file; raw operator logs remain authoritative.
"""
import csv
import hashlib
import json
from pathlib import Path


class AnalysisRecorder:
    def __init__(self, directory, run):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.run = run
        self.pending = self.directory / '.pending.jsonl'
        # A new process cannot safely associate its predecessor's partial match.
        self.pending.write_text('', encoding='utf-8')
        self.pending.chmod(0o600)
        self.round_index = 0
        self.sequence = 0

    def observe(self, record):
        event = record.get('event', '')
        evaluation = record.get('evaluation') or {}
        if not (evaluation or event in {'reaction_win', 'outcome_observed', 'self_win_frame'}):
            return
        self.sequence += 1
        state = evaluation.get('state') or {}
        decision = evaluation.get('decision') or {}
        row = {
            'schemaVersion': 1, 'run': self.run, 'sequence': self.sequence,
            'timestamp': record.get('timestamp'), 'event': event,
            'roundIndex': self.round_index, 'round': state.get('round'),
            'honba': state.get('honba'), 'turn': state.get('turn'),
            'state': state or None, 'decision': decision or None,
            'recognition': evaluation.get('recognition'),
            'timing': {k: evaluation[k] for k in ('processingElapsedMs', 'operatorTiming', 'turnTiming', 'actionTiming', 'publicCache') if k in evaluation},
            'execution': record.get('execution'),
            'evidence': record.get('evidence') or {'screenshot': record.get('screenshot')},
            'outcomeKind': record.get('kind'), 'winId': record.get('winId'),
            'valueSource': 'screen_recognition_and_strategy_estimates',
            'confirmedResult': None,
        }
        with self.pending.open('a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
        if event == 'outcome_observed' and record.get('kind') == 'round':
            self.round_index += 1
        if event == 'outcome_observed' and record.get('kind') == 'match':
            evidence = record.get('evidence') or {}
            screenshot = evidence.get('screenshot')
            if not screenshot:
                return
            match_id = hashlib.sha256(screenshot.encode()).hexdigest()[:16]
            target = self.directory / match_id
            # Repeated result detections must not replace a complete export.
            if not target.exists():
                temp = self.directory / ('.' + match_id)
                temp.mkdir(exist_ok=True)
                rows = [json.loads(line) for line in self.pending.read_text(encoding='utf-8').splitlines()]
                with (temp / 'events.jsonl').open('w', encoding='utf-8') as f:
                    for item in rows:
                        item['matchId'] = match_id
                        f.write(json.dumps(item, ensure_ascii=False) + '\n')
                with (temp / 'decisions.csv').open('w', newline='', encoding='utf-8-sig') as f:
                    fields = ['matchId','timestamp','roundIndex','round','honba','turn','action','tile','clicked','confidence','scores','hand','draw','doraIndicators','ownDiscards','melds','opponents','remainingTiles','candidates','safety','handPlan','timing','screenshot']
                    writer = csv.DictWriter(f, fieldnames=fields)
                    writer.writeheader()
                    for item in rows:
                        if not item['decision'] and not item['execution']:
                            continue
                        state = item['state'] or {}
                        dec = item['decision'] or {}
                        ex = item['execution'] or {}
                        selected = dec.get('selectedAction') or {}
                        result = {k: item.get(k) for k in fields}
                        result.update({k: state.get(k) for k in ('scores','hand','draw','doraIndicators','ownDiscards','melds','opponents','remainingTiles')})
                        result.update({k: dec.get(k) for k in ('candidates','safety','handPlan','confidence')})
                        result.update(action=ex.get('action') or selected.get('action'),tile=selected.get('tile'),clicked=ex.get('clicked'),screenshot=item['evidence'].get('screenshot'))
                        writer.writerow({k: json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in result.items()})
                temp.rename(target)
            self.pending.write_text('', encoding='utf-8')
            self.round_index = 0


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    parser.add_argument('--output', default='artifacts/analysis')
    args = parser.parse_args()
    root = Path(args.root).resolve()
    runs = 0
    malformed = 0
    for log in sorted((root / 'artifacts').glob('**/python-operator.jsonl')):
        run = str(log.parent.relative_to(root))
        run_id = hashlib.sha256(run.encode()).hexdigest()[:16]
        recorder = AnalysisRecorder(Path(args.output) / run_id, run)
        with log.open(encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                recorder.observe(record)
        recorder.pending.unlink(missing_ok=True)
        runs += 1
    print(json.dumps({'runs':runs,'malformedLines':malformed,'output':args.output}))
