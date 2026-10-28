"""DataJanitor — Phase 5 tests: file retention and cleanup rules."""

import os
import time
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.database.base import utcnow
from app.models.records import AuditRow, DatasetRow, PlanRow, ScanRow
from app.services.maintenance_service import run_cleanup

CSV = "id,name\n1,Al\n2,Bo\n3,Cy\n"
HEX = "0123456789abcdef" * 2


async def upload(client):
    r = await client.post("/api/datasets/upload", files={"file": ("d.csv", CSV.encode(), "text/csv")})
    return r.json()["dataset_id"]


def age_file(path, hours):
    t = time.time() - hours * 3600
    os.utime(path, (t, t))


async def test_expired_dataset_file_removed_record_kept_plans_stale(client, db, settings):
    did = await upload(client)
    plan = (await client.post(f"/api/datasets/{did}/repair-plan")).json()
    future = utcnow() + timedelta(days=settings.upload_retention_days + 1)
    report = run_cleanup(db, settings, now=future)
    assert report.expired_datasets == [did] and report.plans_marked_stale == 1
    assert not (settings.upload_path / f"{did}.csv").exists()
    row = db.get(DatasetRow, did)
    assert row.status == "expired" and row.file_removed_at is not None
    assert db.get(PlanRow, plan["plan_id"]).status == "stale"
    assert db.query(ScanRow).filter_by(dataset_id=did).count() == 1   # history kept
    kinds = [a.event_type for a in db.scalars(select(AuditRow))]
    assert "dataset_expired" in kinds and "cleanup_run" in kinds
    assert (await client.post(f"/api/datasets/{did}/scan")).status_code == 410


async def test_dataset_inside_retention_window_is_kept(client, db, settings):
    did = await upload(client)
    report = run_cleanup(db, settings, now=utcnow() + timedelta(days=settings.upload_retention_days - 1))
    assert report.total_changes() == 0
    assert (settings.upload_path / f"{did}.csv").exists()


async def test_dry_run_changes_nothing(client, db, settings):
    did = await upload(client)
    (settings.upload_path / "stale.tmp").write_bytes(b"x")
    age_file(settings.upload_path / "stale.tmp", 5)
    before = db.query(AuditRow).count()
    report = run_cleanup(db, settings, dry_run=True,
                         now=utcnow() + timedelta(days=settings.upload_retention_days + 1))
    assert report.expired_datasets == [did] and report.temp_files == ["stale.tmp"]
    assert (settings.upload_path / f"{did}.csv").exists()
    assert (settings.upload_path / "stale.tmp").exists()
    assert db.get(DatasetRow, did).status == "active"
    assert db.query(AuditRow).count() == before


async def test_orphans_removed_only_after_grace_period(client, db, settings):
    await upload(client)  # makes the folder
    old = settings.upload_path / f"{HEX}.csv"
    new = settings.upload_path / f"{'ab' * 16}.csv"
    old.write_bytes(b"a,b\n1,2\n")
    new.write_bytes(b"a,b\n1,2\n")
    age_file(old, settings.orphan_grace_hours + 1)
    report = run_cleanup(db, settings)
    assert report.orphan_files == [old.name]
    assert not old.exists() and new.exists()


async def test_recorded_dataset_is_never_treated_as_orphan(client, db, settings):
    did = await upload(client)
    path = settings.upload_path / f"{did}.csv"
    age_file(path, 24 * 20)  # old, but recorded and inside retention
    assert run_cleanup(db, settings).total_changes() == 0 and path.exists()


async def test_only_matching_files_are_touched(client, db, settings):
    await upload(client)
    folder = settings.upload_path
    keep = [folder / "notes.txt", folder / "UPPERCASE.csv", folder / f"{HEX}.csv.bak",
            folder / ("short" + ".csv")]
    for f in keep:
        f.write_bytes(b"x")
        age_file(f, 24 * 90)
    (folder / "subdir").mkdir()
    (folder / "subdir" / f"{HEX}.csv").write_bytes(b"x")
    age_file(folder / "subdir" / f"{HEX}.csv", 24 * 90)
    outside = folder.parent / f"{HEX}.csv"
    outside.write_bytes(b"x")
    age_file(outside, 24 * 90)
    run_cleanup(db, settings)
    assert all(f.exists() for f in keep)
    assert (folder / "subdir" / f"{HEX}.csv").exists() and outside.exists()


async def test_symlinks_are_skipped(client, db, settings):
    await upload(client)
    target = settings.upload_path.parent / "precious.txt"
    target.write_text("keep me")
    link = settings.upload_path / f"{HEX}.csv"

    try:
        link.symlink_to(target)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is unavailable")
        raise

    run_cleanup(db, settings, now=utcnow() + timedelta(days=400))
    assert link.is_symlink() and target.read_text() == "keep me"


async def test_old_temp_files_removed_recent_ones_kept(client, db, settings):
    await upload(client)
    old, new = settings.upload_path / "tmpold.tmp", settings.upload_path / "tmpnew.tmp"
    old.write_bytes(b"x"); new.write_bytes(b"x")
    age_file(old, 3)
    report = run_cleanup(db, settings)
    assert report.temp_files == ["tmpold.tmp"] and not old.exists() and new.exists()


async def test_leftover_file_of_deleted_dataset_removed(client, db, settings):
    did = await upload(client)
    await client.delete(f"/api/datasets/{did}")
    (settings.upload_path / f"{did}.csv").write_bytes(CSV.encode())  # resurrected
    report = run_cleanup(db, settings)
    assert report.leftover_files == [f"{did}.csv"]
    assert not (settings.upload_path / f"{did}.csv").exists()


async def test_cleanup_is_idempotent_and_never_deletes_audit_history(client, db, settings):
    did = await upload(client)
    future = utcnow() + timedelta(days=settings.upload_retention_days + 1)
    run_cleanup(db, settings, now=future)
    audit_before = db.query(AuditRow).count()
    again = run_cleanup(db, settings, now=future)
    assert again.total_changes() == 0 and db.query(AuditRow).count() == audit_before
    assert db.query(AuditRow).filter_by(dataset_id=did).count() >= 2


def test_cleanup_with_missing_folder_is_safe(db, settings):
    assert not settings.upload_path.exists()
    assert run_cleanup(db, settings).total_changes() == 0


# ── Cleaned copies (Phase 6) ────────────────────────────────────────────────

async def test_cleaned_copy_expires_but_record_and_history_stay(client, db, settings):
    csv = "id,name\n1, Al\n2,Bo\n3,Cy\n"
    r = await client.post("/api/datasets/upload", files={"file": ("d.csv", csv.encode(), "text/csv")})
    did = r.json()["dataset_id"]
    pid = (await client.post(f"/api/datasets/{did}/repair-plan")).json()["plan_id"]
    await client.post(f"/api/repair-plans/{pid}/approve-safe")
    cid = (await client.post(f"/api/repair-plans/{pid}/apply")).json()["cleaned_id"]
    path = settings.cleaned_path / f"{cid}.csv"
    assert path.exists()
    inside = run_cleanup(db, settings, now=utcnow() + timedelta(days=settings.cleaned_retention_days - 1))
    assert inside.expired_cleaned == [] and path.exists()
    report = run_cleanup(db, settings, now=utcnow() + timedelta(days=settings.cleaned_retention_days + 1))
    assert report.expired_cleaned == [cid] and not path.exists()
    assert (await client.get(f"/api/cleaned/{cid}")).json()["status"] == "expired"
    assert (await client.get(f"/api/cleaned/{cid}/download")).status_code == 410
    assert (settings.upload_path / f"{did}.csv").exists()          # the original is NOT on the cleaned clock
    assert "cleaned_expired" in [a.event_type for a in db.scalars(select(AuditRow))]


async def test_cleaned_folder_orphans_and_temp_files_are_swept_safely(client, db, settings):
    settings.cleaned_path.mkdir(parents=True, exist_ok=True)
    orphan = settings.cleaned_path / f"{HEX}.csv"
    fresh = settings.cleaned_path / f"{'cd' * 16}.csv"
    tmp = settings.cleaned_path / "tmpx.tmp"
    other = settings.cleaned_path / "readme.txt"
    for f in (orphan, fresh, tmp, other):
        f.write_bytes(b"x")
    age_file(orphan, settings.orphan_grace_hours + 1)
    age_file(tmp, 3)
    age_file(other, 24 * 90)
    report = run_cleanup(db, settings)
    assert report.orphan_files == [orphan.name] and report.temp_files == ["tmpx.tmp"]
    assert not orphan.exists() and not tmp.exists() and fresh.exists() and other.exists()


async def test_cleaned_dry_run_changes_nothing(client, db, settings):
    csv = "id,name\n1, Al\n2,Bo\n3,Cy\n"
    did = (await client.post("/api/datasets/upload", files={"file": ("d.csv", csv.encode(), "text/csv")})).json()["dataset_id"]
    pid = (await client.post(f"/api/datasets/{did}/repair-plan")).json()["plan_id"]
    await client.post(f"/api/repair-plans/{pid}/approve-safe")
    cid = (await client.post(f"/api/repair-plans/{pid}/apply")).json()["cleaned_id"]
    report = run_cleanup(db, settings, dry_run=True,
                         now=utcnow() + timedelta(days=settings.cleaned_retention_days + 1))
    assert report.expired_cleaned == [cid]
    assert (settings.cleaned_path / f"{cid}.csv").exists()
    assert (await client.get(f"/api/cleaned/{cid}")).json()["status"] == "completed"
