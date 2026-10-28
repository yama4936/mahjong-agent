"""Optional, bounded asynchronous screencast receipt recording."""

import json
import queue
import threading
import time
from pathlib import Path


class ScreencastDiagnostic:
    def __init__(self, directory, *, capacity=64, duration=30.0):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.queue = queue.Queue(maxsize=capacity)
        self.duration = duration
        self.first_receipt = None
        self.dropped = []
        self.errors = []
        self.closed = threading.Event()
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def offer(self, sequence, receipt, metadata, frame):
        if self.first_receipt is None:
            self.first_receipt = receipt
        if receipt - self.first_receipt > self.duration or self.closed.is_set():
            return
        try:
            self.queue.put_nowait((sequence, receipt, metadata, frame))
        except queue.Full:
            self.dropped.append(sequence)

    def _write(self, item):
        sequence, receipt, metadata, frame = item
        name = f"{sequence:08d}.jpg"
        (self.directory / name).write_bytes(frame)
        with (self.directory / "receipts.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"sequence": sequence, "receiptMonotonic": receipt,
                                     "cdpMetadata": metadata, "file": name}) + "\n")

    def _run(self):
        while not self.closed.is_set() or not self.queue.empty():
            try:
                item = self.queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                self._write(item)
            except Exception as error:
                self.errors.append({"sequence": item[0], "error": str(error)})
            finally:
                self.queue.task_done()

    def close(self, timeout=2.0):
        self.closed.set()
        self.worker.join(timeout)
        return {"droppedSequences": list(self.dropped), "writeErrors": list(self.errors),
                "pending": self.queue.qsize(), "workerAlive": self.worker.is_alive()}
