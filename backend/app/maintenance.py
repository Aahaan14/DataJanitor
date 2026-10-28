"""
DataJanitor — maintenance command line.

    python -m app.maintenance cleanup --dry-run     # preview
    python -m app.maintenance cleanup               # apply the retention rules
"""

import argparse

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.base import make_engine
from app.database.init_db import init_schema
from app.services.maintenance_service import run_cleanup


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.maintenance")
    sub = parser.add_subparsers(dest="command", required=True)
    clean = sub.add_parser("cleanup", help="apply the file retention rules")
    clean.add_argument("--dry-run", action="store_true", help="report only; change nothing")
    args = parser.parse_args()

    settings = get_settings()
    engine = make_engine(settings.database_url)
    init_schema(engine)
    with Session(engine) as session:
        report = run_cleanup(session, settings, dry_run=args.dry_run)
    mode = "DRY RUN — nothing changed" if report.dry_run else "applied"
    print(f"Cleanup ({mode})")
    print(f"  expired datasets : {len(report.expired_datasets)}")
    print(f"  expired cleaned  : {len(report.expired_cleaned)}")
    print(f"  leftover files   : {len(report.leftover_files)}")
    print(f"  orphan files     : {len(report.orphan_files)}")
    print(f"  temp files       : {len(report.temp_files)}")
    print(f"  plans made stale : {report.plans_marked_stale}")


if __name__ == "__main__":
    main()
