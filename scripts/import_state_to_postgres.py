#!/usr/bin/env python3
"""
Copy the local account state to Supabase Postgres, once, before setting STATE_BACKEND=postgres.

    python scripts/import_state_to_postgres.py --dry-run    # counts only, changes nothing
    python scripts/import_state_to_postgres.py              # stop the app first

It refuses to overwrite a replica that already has data unless given --force. It prints counts
only: the state holds personal data. Steps for the cutover: docs/deployment.md.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.services.state_replica import META_SECTION, PostgresStateClient, to_rows  # noqa: E402
from app.services.state_store import read_json  # noqa: E402

_BATCH_ROWS = 500


def run(dry_run: bool, force: bool) -> int:
    state_file = settings.OUTPUT_DIR / "supabase_cloud_state.json"
    state = read_json(state_file)
    rows = to_rows(state)
    for section, count in sorted(Counter(section for section, _ in rows).items()):
        print(f"{section}: {count}")
    print(f"total rows: {len(rows)}")
    if dry_run:
        print("Dry run: nothing was changed.")
        return 0

    if not (settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY):
        print("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.", file=sys.stderr)
        return 2
    client = PostgresStateClient()
    generation, _ = client.read_meta()
    existing = client.read_rows()
    if existing and not force:
        print(f"The replica already has {len(existing)} rows. Use --force to replace them.", file=sys.stderr)
        return 3

    client.set_importing(True)  # an app starting meanwhile refuses to use a half-imported replica
    upserts = [{"section": s, "key": k, "value": v} for (s, k), v in rows.items()]
    deletes = [{"section": r["section"], "key": r["key"]} for r in existing if (r["section"], r["key"]) not in rows]
    for start in range(0, max(len(upserts), 1), _BATCH_ROWS):
        batch = upserts[start:start + _BATCH_ROWS]
        client.apply(generation, generation, batch, deletes if start == 0 else [])
    final = max(int((state.get(META_SECTION) or {}).get("generation") or 0), generation) + 1
    client.apply(generation, final, [], [])
    client.set_importing(False)

    # The app compares this number at start-up: both sides must agree that they hold the same state.
    state[META_SECTION] = {"generation": final}
    from app.services.state_store import atomic_write_json

    atomic_write_json(state_file, state)
    print(f"Imported {len(upserts)} rows at generation {final}.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="only count what would be imported")
    parser.add_argument("--force", action="store_true", help="replace a replica that already has data")
    arguments = parser.parse_args()
    sys.exit(run(arguments.dry_run, arguments.force))
