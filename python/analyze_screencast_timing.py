"""Inspect diagnostic clocks; never use these estimates for action safety.

CDP timestamp and the receiver wall clock may have different offsets or jump.
The reported wall-minus-CDP value is therefore only an uncalibrated estimate.
"""
import argparse
import json
import math


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def analyze(records):
    previous = None
    for record in records:
        metadata = record.get("cdpMetadata") or {}
        timestamp = metadata.get("timestamp") if isinstance(metadata, dict) else None
        receipt = record.get("receiptMonotonic")
        wall = record.get("receiptWallTime")
        sequence = record.get("sequence")
        result = {"sequence": sequence, "issues": []}
        if not finite_number(timestamp):
            result["issues"].append("missing_or_invalid_cdp_timestamp")
        if not finite_number(receipt):
            result["issues"].append("missing_or_invalid_monotonic_receipt")
        if not finite_number(wall):
            result["issues"].append("missing_or_invalid_wall_receipt")
        if finite_number(timestamp) and finite_number(wall):
            result["uncalibratedWallMinusCdpMs"] = round((wall - timestamp) * 1000, 3)
        if previous is not None:
            prev_sequence, prev_timestamp, prev_receipt, prev_wall = previous
            if isinstance(sequence, int) and isinstance(prev_sequence, int) and sequence != prev_sequence + 1:
                result["issues"].append("sequence_gap_or_reordering")
            if finite_number(timestamp) and finite_number(prev_timestamp):
                delta = timestamp - prev_timestamp
                result["cdpIntervalMs"] = round(delta * 1000, 3)
                if delta <= 0:
                    result["issues"].append("cdp_timestamp_not_increasing")
            if finite_number(receipt) and finite_number(prev_receipt):
                delta = receipt - prev_receipt
                result["receiptIntervalMs"] = round(delta * 1000, 3)
                if delta <= 0:
                    result["issues"].append("receipt_not_increasing")
                if finite_number(wall) and finite_number(prev_wall) and abs((wall - prev_wall) - delta) > 0.05:
                    result["issues"].append("wall_clock_discontinuity")
        previous = sequence, timestamp, receipt, wall
        yield result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipts", help="screencast diagnostic receipts.jsonl")
    args = parser.parse_args()
    with open(args.receipts, encoding="utf-8") as stream:
        for result in analyze(json.loads(line) for line in stream if line.strip()):
            print(json.dumps(result))


if __name__ == "__main__":
    main()
