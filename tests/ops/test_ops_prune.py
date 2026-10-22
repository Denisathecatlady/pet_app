"""Retention of deploy/backup_db.sh: newest 30 backups + first backup of each of the last 12 months.

Pruning is tested without a database (``--prune-only``) on fake files with controlled names.
The reference implementation below is written independently of the shell code. Names more
than a day ahead of the clock are not part of the rule (see the end of this file).
"""

import os
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.ops.helpers import DEPLOY_DIR

STAMP_FORMAT = "%Y%m%dT%H%M%SZ"


def name_of(stamp: str) -> str:
    return f"barf-{stamp}.dump.gpg"


def create_backups(directory: Path, stamps: list[str]) -> None:
    """Fake backups: a file and its manifest for every stamp."""
    for stamp in stamps:
        (directory / name_of(stamp)).write_bytes(b"encrypted " + stamp.encode())
        (directory / (name_of(stamp) + ".sha256")).write_text(f"manifest {stamp}\n")


def prune(directory: Path, path: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(DEPLOY_DIR / "backup_db.sh"), "--prune-only"],
        env={"PATH": path or os.environ["PATH"], "BACKUP_DIR": str(directory), "LANG": "C"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def survivors(directory: Path, created: list[str]) -> set[str]:
    """Which of the ``created`` stamps still have a backup file (``.dump.gpg``)."""
    return {stamp_ for stamp_ in created if (directory / name_of(stamp_)).exists()}


def expected_survivors(stamps: list[str]) -> set[str]:
    """Reference: newest 30 files + the earliest file of each of the 12 newest calendar months."""
    ordered = sorted(set(stamps))
    kept = set(ordered[-30:])
    newest = datetime.strptime(ordered[-1], STAMP_FORMAT).replace(tzinfo=UTC)
    window = set()
    year, month = newest.year, newest.month
    for _ in range(12):
        window.add(f"{year:04d}{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    for month_key in window:
        in_month = [stamp for stamp in ordered if stamp.startswith(month_key)]
        if in_month:
            kept.add(in_month[0])
    return kept


def at(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


def stamp(moment: datetime) -> str:
    return moment.strftime(STAMP_FORMAT)


def test_prune_keeps_the_newest_30_and_the_first_backup_of_the_last_12_months(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    newest = at(2025, 3, 15, 2)
    daily = [stamp(newest - timedelta(days=k)) for k in range(60)]
    twice_monthly = [
        stamp(at(year, month, day, 1))
        for year, month in [(2023, m) for m in range(6, 13)]
        + [(2024, m) for m in range(1, 13)]
        + [(2025, 1), (2025, 2)]
        for day in (3, 17)
    ]
    create_backups(directory, daily + twice_monthly)

    result = prune(directory)

    assert result.returncode == 0, result.stderr
    left = survivors(directory, daily + twice_monthly)
    # The newest 30 files are the daily ones of 2025-02-15 .. 2025-03-15 (29) and the file of
    # 2025-02-17 01:00; in addition the first backup of 2024-04 .. 2025-02 (11 months).
    assert len(left) == 41
    assert left == expected_survivors(daily + twice_monthly)
    assert "20250215T020000Z" in left  # oldest of the newest 30
    assert "20250214T020000Z" not in left  # one older
    assert "20240403T010000Z" in left  # first backup of the oldest month in the window
    assert "20240417T010000Z" not in left  # second backup of that month
    assert "20240303T010000Z" not in left  # month outside the window
    assert "20230603T010000Z" not in left
    assert "20250301T020000Z" in left  # first of March (is also among the newest 30)
    assert "20250103T010000Z" in left  # first of January, older than the newest 30
    assert "20250117T010000Z" not in left
    # Every manifest follows its file: kept files keep theirs, deleted files lose theirs.
    manifests = {
        path.name.removeprefix("barf-").removesuffix(".dump.gpg.sha256")
        for path in directory.glob("barf-*.sha256")
    }
    assert manifests == left


def test_prune_is_idempotent_and_a_noop_below_the_limit(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    stamps = [stamp(at(2026, 1, 1) + timedelta(days=k)) for k in range(30)]
    create_backups(directory, stamps)

    assert prune(directory).returncode == 0
    assert survivors(directory, stamps) == set(stamps)
    assert prune(directory).returncode == 0
    assert survivors(directory, stamps) == set(stamps)


def test_the_newest_30_are_kept_however_old_they_are(tmp_path):
    """After a long outage the last good backups are not thrown away."""
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    stamps = [stamp(at(2019, 5, 1) + timedelta(days=40 * k)) for k in range(10)]
    create_backups(directory, stamps)

    assert prune(directory).returncode == 0
    assert survivors(directory, stamps) == set(stamps)


def test_several_backups_on_one_day_each_count_as_a_backup(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    stamps = [stamp(at(2026, 5, 1, hour)) for hour in range(24)]
    stamps += [stamp(at(2026, 5, 2, hour)) for hour in range(12)]
    create_backups(directory, stamps)

    assert prune(directory).returncode == 0
    left = survivors(directory, stamps)
    assert left == expected_survivors(stamps)
    assert len(left) == 31  # the newest 30, and the first backup of May in addition
    assert "20260501T000000Z" in left
    assert "20260501T050000Z" not in left


NOT_BACKUPS = {
    "README.txt": b"documentation",
    "barf-20230101T000000Z.dump": b"not .gpg",
    "barf-20230101T000000Z.dump.gpg.bak": b"suffix",
    "barf-20230101T000000Z.dump.gpg.sha256.bak": b"suffix",
    "barf-2023.dump.gpg": b"short",
    "other-20230101T000000Z.dump.gpg": b"prefix",
    "xbarf-20230101T000000Z.dump.gpg": b"prefix",
    "BARF-20230101T000000Z.dump.gpg": b"case",
    "barf-20231301T000000Z.dump.gpg": b"month 13",
    "barf-20230132T000000Z.dump.gpg": b"day 32",
    "barf-20230101T250000Z.dump.gpg": b"hour 25",
    "barf-20230101T006000Z.dump.gpg": b"minute 60",
    "barf-20230101T000000Zxdump.gpg": b"dot is literal",
    "barf-20230101T000000Z.dump.gpg~": b"editor backup",
    ".barf-partial.abc123": b"partial",
    "notes.sha256": b"manifest-like",
}


def test_prune_deletes_only_files_that_match_the_backup_name_exactly(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    for name, content in NOT_BACKUPS.items():
        (directory / name).write_bytes(content)
    # A directory and a symbolic link with a backup name are not backups either.
    folder = directory / name_of("20230105T000000Z")
    folder.mkdir()
    (folder / "inside.txt").write_text("keep")
    link = directory / name_of("20230106T000000Z")
    link.symlink_to(directory / "README.txt")
    # Real (fake) backups: 35 daily ones, so the oldest five are deleted.
    stamps = [stamp(at(2026, 2, 1, 3) + timedelta(days=k)) for k in range(35)]
    create_backups(directory, stamps)
    # A manifest whose backup is gone is removed as well.
    orphan = directory / (name_of("20230107T000000Z") + ".sha256")
    orphan.write_text("orphan")

    result = prune(directory)

    assert result.returncode == 0, result.stderr
    for name, content in NOT_BACKUPS.items():
        assert (directory / name).read_bytes() == content, name
    assert (folder / "inside.txt").read_text() == "keep"
    assert link.is_symlink()
    assert link.resolve() == (directory / "README.txt").resolve()
    assert (directory / "README.txt").read_bytes() == b"documentation"
    assert not orphan.exists()
    left = survivors(directory, stamps)
    assert left == expected_survivors(stamps)
    assert len(left) == 30 + 1  # the first backup of February is kept in addition


def test_prune_only_needs_nothing_but_backup_dir(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    create_backups(directory, ["20260101T000000Z"])

    result = prune(directory)

    assert result.returncode == 0, result.stderr
    assert survivors(directory, ["20260101T000000Z"]) == {"20260101T000000Z"}


def test_prune_refuses_a_world_readable_directory(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    stamps = [stamp(at(2024, 1, 1) + timedelta(days=k)) for k in range(40)]
    create_backups(directory, stamps)

    result = prune(directory)

    assert result.returncode == 2
    assert survivors(directory, stamps) == set(stamps)


def test_prune_of_an_empty_directory_is_fine(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)

    assert prune(directory).returncode == 0


@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    # 2022-11-20 + 1200 days is early March 2026: every name lies in the past (names ahead of
    # the clock are ignored by design, see the tests below).
    offsets=st.lists(st.integers(min_value=0, max_value=1200 * 24 * 3600), min_size=1, max_size=90)
)
def test_prune_matches_the_reference_for_random_names(offsets):
    base = at(2022, 11, 20, 12)
    stamps = sorted({stamp(base + timedelta(seconds=offset)) for offset in offsets})
    with tempfile.TemporaryDirectory(prefix="prune") as root:
        directory = Path(root)
        directory.chmod(0o700)
        create_backups(directory, stamps)

        result = prune(directory)

        assert result.returncode == 0, result.stderr
        assert survivors(directory, stamps) == expected_survivors(stamps)


# --- Names ahead of the clock: a set-back clock or a stray file must not wipe the history --------


def month_of_each(year: int, first: int, last: int) -> list[str]:
    """Three fake backups (the 1st, 10th and 20th) in every month of ``year`` from first to last."""
    return [
        stamp(at(year, month, day, 1)) for month in range(first, last + 1) for day in (1, 10, 20)
    ]


def test_a_future_dated_name_does_not_wipe_the_monthly_history(tmp_path):
    """One file named 2099 used to become the "newest" backup: the 12 month window then
    started in 2098 and every real monthly backup was deleted."""
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    real = month_of_each(2025, 11, 12) + month_of_each(2026, 1, 10)
    future = "20991231T235959Z"
    create_backups(directory, [*real, future])

    result = prune(directory)

    assert result.returncode == 0, result.stderr
    left = survivors(directory, real)
    assert left == expected_survivors(real)
    for month in range(11, 13):
        assert f"2025{month}01T010000Z" in left  # the monthly firsts of the real history
    assert "20250" not in "".join(left)
    assert (directory / name_of(future)).exists()
    assert (directory / (name_of(future) + ".sha256")).exists()
    assert "WARNING" in result.stderr and name_of(future) in result.stderr
    assert "1 ignored" in result.stderr


def test_many_future_names_are_neither_counted_nor_deleted(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    real = [stamp(at(2026, 5, 1) + timedelta(days=k)) for k in range(40)]
    future = [stamp(at(2030, 11, 1) + timedelta(days=k)) for k in range(35)]
    create_backups(directory, real + future)

    result = prune(directory)

    assert result.returncode == 0, result.stderr
    assert survivors(directory, future) == set(future)  # all 35 kept, none counted
    assert survivors(directory, real) == expected_survivors(real)  # as if they were not there


def test_a_name_within_the_tolerance_counts_as_a_backup(tmp_path):
    """A clock that is a few hours off is a normal backup, not a future one."""
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    soon = stamp(datetime.now(UTC) + timedelta(hours=3))
    old = [stamp(at(2026, 1, 1) + timedelta(days=k)) for k in range(35)]
    create_backups(directory, [*old, soon])

    result = prune(directory)

    assert result.returncode == 0, result.stderr
    assert "0 ignored" in result.stderr
    assert (directory / name_of(soon)).exists()
    assert survivors(directory, old) == expected_survivors([*old, soon]) - {soon}


def test_a_name_just_beyond_the_tolerance_is_ignored(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    beyond = stamp(datetime.now(UTC) + timedelta(days=2))
    create_backups(directory, [beyond])

    result = prune(directory)

    assert result.returncode == 0, result.stderr
    assert (directory / name_of(beyond)).exists()
    assert "1 ignored" in result.stderr
