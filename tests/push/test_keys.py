"""The VAPID key pair on disk: the private key decides, the public file follows."""

import os
import stat
from pathlib import Path

import pytest

from trainer.push import keys
from trainer.push.keys import KeysError, KeysResult, write_keys
from trainer.services.webpush import VapidKey


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def pair(directory: Path) -> tuple[VapidKey, str]:
    """The private key on disk, and the public key its public file names."""
    private = read(directory / "push.env").strip().partition("=")[2]
    public = read(directory / "push-public.env").strip()
    return VapidKey.from_text(private), public


def test_the_first_run_makes_a_matching_pair(tmp_path: Path) -> None:
    assert write_keys(tmp_path, rotate=False) is KeysResult.MADE

    key, public = pair(tmp_path)
    assert read(tmp_path / "push.env") == f"TRAINER_VAPID_PRIVATE_KEY={key.text}\n"
    assert public == f"TRAINER_VAPID_PUBLIC_KEY={key.public_text}"
    for name in ("push.env", "push-public.env"):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600
    assert sorted(path.name for path in tmp_path.iterdir()) == ["push-public.env", "push.env"]


def test_later_runs_keep_the_pair(tmp_path: Path) -> None:
    write_keys(tmp_path, rotate=False)
    before = read(tmp_path / "push.env"), read(tmp_path / "push-public.env")

    assert write_keys(tmp_path, rotate=False) is KeysResult.KEPT

    assert (read(tmp_path / "push.env"), read(tmp_path / "push-public.env")) == before


def test_a_rotation_makes_a_new_matching_pair(tmp_path: Path) -> None:
    write_keys(tmp_path, rotate=False)
    old, _ = pair(tmp_path)

    assert write_keys(tmp_path, rotate=True) is KeysResult.MADE

    new, public = pair(tmp_path)
    assert new.text != old.text
    assert public == f"TRAINER_VAPID_PUBLIC_KEY={new.public_text}"


def test_a_rotation_cut_short_is_put_right_by_the_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_keys(tmp_path, rotate=False)
    written = keys._write  # noqa: SLF001  # why: interrupt the run between its two files
    calls: list[Path] = []

    def die_after_the_private_file(path: Path, text: str) -> None:
        calls.append(path)
        if path.name == "push-public.env":
            raise SystemExit
        written(path, text)

    monkeypatch.setattr(keys, "_write", die_after_the_private_file)
    with pytest.raises(SystemExit):
        write_keys(tmp_path, rotate=True)
    monkeypatch.undo()
    new, public = pair(tmp_path)
    assert public != f"TRAINER_VAPID_PUBLIC_KEY={new.public_text}"  # the mismatch

    assert write_keys(tmp_path, rotate=False) is KeysResult.REPAIRED

    key, public = pair(tmp_path)
    assert key.text == new.text  # the private key decides
    assert public == f"TRAINER_VAPID_PUBLIC_KEY={key.public_text}"
    assert [path.name for path in calls] == ["push.env", "push-public.env"]


def test_a_missing_public_file_is_written_again(tmp_path: Path) -> None:
    write_keys(tmp_path, rotate=False)
    (tmp_path / "push-public.env").unlink()

    assert write_keys(tmp_path, rotate=False) is KeysResult.REPAIRED

    key, public = pair(tmp_path)
    assert public == f"TRAINER_VAPID_PUBLIC_KEY={key.public_text}"


def test_the_private_key_is_found_among_other_lines(tmp_path: Path) -> None:
    key = VapidKey.generate()
    (tmp_path / "push.env").write_text(
        f"# made earlier\nOTHER=1\nTRAINER_VAPID_PRIVATE_KEY= {key.text} \n"
    )

    assert write_keys(tmp_path, rotate=False) is KeysResult.REPAIRED

    public = read(tmp_path / "push-public.env")
    assert public == f"TRAINER_VAPID_PUBLIC_KEY={key.public_text}\n"


def test_a_private_file_without_a_key_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / "push.env").write_text("OTHER=1\n")

    with pytest.raises(KeysError, match="holds no TRAINER_VAPID_PRIVATE_KEY"):
        write_keys(tmp_path, rotate=False)

    assert read(tmp_path / "push.env") == "OTHER=1\n"
    assert not (tmp_path / "push-public.env").exists()


def test_files_are_owner_only_whatever_the_umask(tmp_path: Path) -> None:
    old = os.umask(0)
    try:
        write_keys(tmp_path, rotate=False)
    finally:
        os.umask(old)

    for name in ("push.env", "push-public.env"):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600


def test_a_padded_private_key_is_read_whole(tmp_path: Path) -> None:
    key = VapidKey.generate()
    (tmp_path / "push.env").write_text(f"TRAINER_VAPID_PRIVATE_KEY={key.text}=\n")

    assert write_keys(tmp_path, rotate=False) is KeysResult.REPAIRED

    assert read(tmp_path / "push-public.env") == f"TRAINER_VAPID_PUBLIC_KEY={key.public_text}\n"


def test_a_stale_staged_file_is_replaced_owner_only(tmp_path: Path) -> None:
    # From review: O_TRUNC keeps an existing file's mode, so a staged file left
    # over at 0644 would have carried the private key out at 0644.
    for name in (".push.env.new", ".push-public.env.new"):
        (tmp_path / name).write_text("left over, and longer than any key line in the file")
        (tmp_path / name).chmod(0o644)

    write_keys(tmp_path, rotate=False)

    assert read(tmp_path / "push.env").startswith("TRAINER_VAPID_PRIVATE_KEY=")
    assert read(tmp_path / "push.env").count("\n") == 1
    for name in ("push.env", "push-public.env"):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600
    assert sorted(path.name for path in tmp_path.iterdir()) == ["push-public.env", "push.env"]


def test_a_short_write_is_finished(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # From review: os.write may write only a prefix; the rest must follow.
    real = os.write
    sizes: list[int] = []

    def a_few_bytes_at_a_time(descriptor: int, data: bytes) -> int:
        sizes.append(real(descriptor, bytes(data[:5])))
        return sizes[-1]

    monkeypatch.setattr(os, "write", a_few_bytes_at_a_time)
    write_keys(tmp_path, rotate=False)
    monkeypatch.undo()

    key, public = pair(tmp_path)
    assert public == f"TRAINER_VAPID_PUBLIC_KEY={key.public_text}"
    assert max(sizes) == 5
    assert len(sizes) > 2


def test_a_write_that_stops_promotes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_keys(tmp_path, rotate=False)
    before = read(tmp_path / "push.env")
    real = os.write

    def stalls(descriptor: int, data: bytes) -> int:
        return 0 if len(data) < 20 else real(descriptor, bytes(data[:10]))

    monkeypatch.setattr(os, "write", stalls)
    with pytest.raises(OSError, match=r"^no progress writing a key file$"):
        write_keys(tmp_path, rotate=True)
    monkeypatch.undo()

    assert read(tmp_path / "push.env") == before  # the old key is still whole
