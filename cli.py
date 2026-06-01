import json
import sys

from services.compare_service import compare_latest_previous, list_snapshots
from services.db import init_db
from services.snapshot_service import take_snapshot


def main() -> int:
    init_db()
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if command == "snapshot":
            result = take_snapshot(source="cli")
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if command == "compare-latest":
            print(json.dumps(compare_latest_previous(), indent=2))
            return 0
        if command == "list-snapshots":
            print(json.dumps(list_snapshots(), indent=2))
            return 0
        print("Usage: python cli.py {snapshot|compare-latest|list-snapshots}")
        return 1
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
