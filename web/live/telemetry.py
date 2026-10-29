"""Bounded, read-only public projection of operator JSONL telemetry."""
from collections import deque
from datetime import datetime
from pathlib import Path
import json
import math
import re
import time
import uuid


MESSAGES = {
    'decision': '判断を更新',
    'click_sent': '操作クリックを送信',
    'action_click_sent': 'アクションボタンをクリック',
    'started': '操作者を開始',
    'rearmed': '次の手番を待機',
    'reaction_prompt': '鳴き・和了の選択を検出',
    'reaction_call_policy_rejected': '鳴きを見送り',
    'own_discard_reconciled': '打牌を確認',
    'action_aborted': '操作を中断し再確認',
    'force_auto_click_budget_expired': '操作時間の予算を超過',
    'recognition_deferred_stale_capture': '画面を再取得して認識待ち',
    'recognition_deferred': '認識を再確認',
    'outcome_observed': '局・対局結果を確認',
    'terminal': '操作者を終了',
    'ranked_click_budget_safety_stop': '操作時間超過により停止',
    'away_resumed': '離席から復帰',
    'screen_advanced': '次の画面へ進行',
}
ACTIONS = {'discard', 'riichi', 'riichi_discard', 'ron', 'tsumo', 'chi',
           'pon', 'kan', 'ankan', 'kakan', 'daiminkan', 'pass', 'skip', 'wait', 'kyuushu'}
SOURCES = {'jev', 'local', 'heuristic', 'fallback', 'local_fallback', 'rule', 'rules'}
MAX_BYTES = 512 * 1024


def mapping(value):
    return value if isinstance(value, dict) else {}


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


def probability(value):
    return value if type(value) in (float, int) and 0 <= value <= 1 and math.isfinite(value) else None


def tile(value):
    return value if isinstance(value, str) and re.fullmatch(r'(?:[0-9][mps]|[ESWNPFC])', value) else None


def public_decision(record):
    evaluation = mapping(record.get('evaluation'))
    decision = mapping(evaluation.get('decision'))
    recognition = mapping(evaluation.get('recognition'))
    selected = mapping(decision.get('selectedAction'))
    action = selected.get('action', decision.get('recommendedAction'))
    action = action if isinstance(action, str) and action in ACTIONS else None
    chosen_tile = tile(selected.get('tile', decision.get('tile')))
    candidates = decision.get('candidates')
    candidates = [c for c in candidates if isinstance(c, dict)] if isinstance(candidates, list) else []
    selected_id = decision.get('selectedActionId')
    if selected_id is not None:
        matches = [c for c in candidates if isinstance(selected_id, str) and c.get('actionId') == selected_id]
    else:
        matches = [c for c in candidates if action is not None and c.get('action') == action and c.get('tile') == chosen_tile]
    candidate = matches[0] if len(matches) == 1 else {}
    source = decision.get('source')
    shanten = candidate.get('shanten')
    return {
        'timestamp': timestamp(record.get('timestamp')),
        'action': action, 'tile': chosen_tile,
        'source': source if isinstance(source, str) and source in SOURCES else None,
        'winProbability': probability(candidate.get('winProbability')),
        'dealInProbability': probability(candidate.get('dealInProbability')),
        'recognitionConfidence': probability(recognition.get('confidence')),
        'recognitionSafe': recognition.get('safe') if type(recognition.get('safe')) is bool else None,
        'shanten': shanten if type(shanten) is int and -1 <= shanten <= 13 else None,
    }


class Telemetry:
    def __init__(self, root):
        self.root = Path(root) if root else None
        self.path = None
        self.identity = None
        self.offset = 0
        self.partial = b''
        self.skipping = False
        self.discover_at = 0
        self.sequence = 0
        self.instance = uuid.uuid4().hex
        self.logs = deque(maxlen=100)
        self.decision = None
        self.updated_at = None

    def _discover(self):
        now = time.monotonic()
        if now < self.discover_at:
            return
        self.discover_at = now + 1
        best = None
        if self.root:
            for pattern in ('*/python-operator.jsonl', '*/*/python-operator.jsonl'):
                for path in self.root.glob(pattern):
                    try:
                        if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(self.root.resolve()):
                            key = (path.stat().st_mtime_ns, str(path))
                            if best is None or key > best[0]:
                                best = (key, path)
                    except OSError:
                        continue
        path = best[1] if best else None
        if path != self.path:
            self.path = path
            self.identity = None
            self._reset()

    def _reset(self):
        self.offset = 0
        self.partial = b''
        self.skipping = False
        self.decision = None
        self.updated_at = None
        self.logs.clear()

    def _accept(self, line):
        try:
            record = json.loads(line)
        except (ValueError, UnicodeError, RecursionError):
            return
        if not isinstance(record, dict):
            return
        event = record.get('event')
        if not isinstance(event, str) or event not in MESSAGES:
            return
        stamp = timestamp(record.get('timestamp'))
        if stamp is not None:
            self.updated_at = stamp
        if event == 'decision':
            self.decision = public_decision(record)
        elif event in {'outcome_observed', 'terminal', 'ranked_click_budget_safety_stop'}:
            self.decision = None
        self.sequence += 1
        message = MESSAGES[event]
        if event == 'decision' and self.decision['action']:
            message += ': ' + self.decision['action']
            if self.decision['tile']:
                message += ' ' + self.decision['tile']
        self.logs.append({'id': f'{self.instance}:{self.sequence}', 'timestamp': stamp,
                          'event': event, 'message': message})

    def snapshot(self):
        self._discover()
        if self.path:
            try:
                with self.path.open('rb') as stream:
                    stat = self.path.stat()
                    identity = (stat.st_dev, stat.st_ino)
                    if identity != self.identity or stat.st_size < self.offset:
                        self._reset()
                        self.identity = identity
                        self.offset = max(0, stat.st_size - MAX_BYTES)
                        self.skipping = self.offset > 0
                    stream.seek(self.offset)
                    chunk = stream.read(MAX_BYTES)
                    self.offset += len(chunk)
                    data = self.partial + chunk
                    lines = data.split(b'\n')
                    self.partial = lines.pop()
                    for line in lines:
                        if self.skipping:
                            self.skipping = False
                        else:
                            self._accept(line)
                    if len(self.partial) > MAX_BYTES:
                        self.partial = b''
                        self.skipping = True
            except OSError:
                self._reset()
        return {'updatedAt': self.updated_at,
                'decision': dict(self.decision) if self.decision else None,
                'logs': [dict(entry) for entry in self.logs]}
