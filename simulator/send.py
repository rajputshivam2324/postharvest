"""Send seeded demo readings through the public, device-authenticated HTTP endpoint."""

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

if __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulator.scenarios import SCENARIOS, generate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, default="stable")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--count", type=int, default=73)
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--start", help="ISO timestamp with timezone; default fills the last 6h")
    parser.add_argument(
        "--run-id", default=None, help="Reuse with identical start/seed for safe retries"
    )
    parser.add_argument("--warmup-samples", type=int, default=0)
    parser.add_argument(
        "--assess", action="store_true", help="Requires ACCESS_TOKEN environment variable"
    )
    args = parser.parse_args()
    if not 1 <= args.count <= 10000 or args.interval_seconds < 1 or args.warmup_samples < 0:
        parser.error("Invalid sample count, interval or warm-up count")
    token = os.environ.get("DEVICE_TOKEN")
    if not token:
        parser.error("Set DEVICE_TOKEN to the simulated device's one-time credential")
    access_token = os.environ.get("ACCESS_TOKEN")
    if args.assess and not access_token:
        parser.error("Set ACCESS_TOKEN to a user JWT before requesting assessment")
    start = (
        datetime.fromisoformat(args.start)
        if args.start
        else datetime.now(UTC) - timedelta(seconds=(args.count - 1) * args.interval_seconds + 1)
    )
    run_id = args.run_id or str(uuid4())
    payloads = generate(
        scenario=args.scenario,
        seed=args.seed,
        start=start,
        count=args.count,
        interval_seconds=args.interval_seconds,
        device_id=args.device_id,
        batch_id=args.batch_id,
        run_id=run_id,
        warmup_samples=args.warmup_samples,
    )
    accepted, duplicates = 0, 0
    try:
        for payload in payloads:
            request = Request(
                args.url.rstrip("/") + "/api/v1/readings",
                data=json.dumps(payload).encode(),
                method="POST",
                headers={"Content-Type": "application/json", "X-Device-Token": token},
            )
            with urlopen(request, timeout=15) as response:
                result = json.load(response)
                duplicates += int(result["duplicate"])
                accepted += int(not result["duplicate"])
        print(
            json.dumps(
                {
                    "scenario": args.scenario,
                    "run_id": run_id,
                    "start": start.isoformat(),
                    "accepted": accepted,
                    "duplicates": duplicates,
                    "simulated": True,
                }
            )
        )
        if args.assess:
            request = Request(
                args.url.rstrip("/") + f"/api/v1/batches/{args.batch_id}/assessments",
                data=b"",
                method="POST",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            with urlopen(request, timeout=30) as response:
                print(json.dumps(json.load(response)))
    except HTTPError as exc:
        parser.exit(
            1, f"Backend rejected request (HTTP {exc.code}); check device, token and payload.\n"
        )
    except URLError:
        parser.exit(1, "Could not reach backend.\n")


if __name__ == "__main__":
    main()
