import json
import sys
from datetime import datetime, timezone

from services.compare_service import compare_latest_previous, list_snapshots
from services.buzz_service import run_buzz_check
from services.db import init_db
from services.snapshot_service import take_snapshot


def main() -> int:
    init_db()
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if command == "snapshot":
            snapshots = list_snapshots()
            if snapshots:
                checked_at = datetime.fromisoformat(snapshots[0]["checked_at"])
                age_minutes = (datetime.now(timezone.utc) - checked_at).total_seconds() / 60
                if age_minutes < 5:
                    print(
                        "Warning: the latest snapshot is less than 5 minutes old; "
                        "the next comparison may not show meaningful growth.",
                        file=sys.stderr,
                    )
            result = take_snapshot(source="cli")
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if command == "compare-latest":
            print(json.dumps(compare_latest_previous(), indent=2))
            return 0
        if command == "list-snapshots":
            print(json.dumps(list_snapshots(), indent=2))
            return 0
        if command == "buzz-check":
            result = run_buzz_check(source="cli")
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        print("Usage: python cli.py {snapshot|compare-latest|list-snapshots|buzz-check}")
        return 1
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
