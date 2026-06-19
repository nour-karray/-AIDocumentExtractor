from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core import quality_score, status_from_payload
from src.config import load_config
from src.services.extraction_history import delete_history_entry, list_history_entries


def _entry_status(entry: dict[str, Any]) -> str:
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    explicit = str(entry.get("status") or "").strip().lower()
    if explicit == "error":
        return "error"
    return status_from_payload(payload)


def _entry_quality(entry: dict[str, Any]) -> float | None:
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    kind = str(entry.get("kind") or "")
    return quality_score(payload, kind)


def _cleanup_reason(entry: dict[str, Any]) -> str | None:
    status = _entry_status(entry)
    if status == "error":
        return "status=error"
    quality = _entry_quality(entry)
    if quality is not None and quality <= 0:
        return "qualityScore=0"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Nettoie l'historique production: supprime les resultats error et qualite 0%."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Applique le nettoyage. Sans cette option, affiche seulement ce qui serait supprime.",
    )
    args = parser.parse_args()

    cfg = load_config(PROJECT_ROOT)
    entries = list_history_entries(cfg)
    targets = [(entry, reason) for entry in entries if (reason := _cleanup_reason(entry))]

    print(f"Historique analyse: {len(entries)} entree(s)")
    print(f"Entrees a nettoyer: {len(targets)}")

    deleted = 0
    failed = 0
    for entry, reason in targets:
        relative = str(entry.get("relative") or "")
        kind = str(entry.get("kind") or "")
        quality = _entry_quality(entry)
        label = f"{relative} | kind={kind} | quality={quality} | reason={reason}"
        if not args.apply:
            print(f"DRY-RUN {label}")
            continue
        ok, message = delete_history_entry(cfg, entry)
        if ok:
            deleted += 1
            print(f"OK {label}")
        else:
            failed += 1
            print(f"FAIL {label} | {message}")

    if not args.apply:
        print("Mode simulation uniquement. Relancer avec --apply pour nettoyer.")
    else:
        print(f"Nettoyage termine: {deleted} supprimee(s), {failed} echec(s).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
