import json
from pathlib import Path

import pytest

import driver_venus.driver_info as driver_info
from driver_venus.driver_info import build_info, load_driver_info, read_board_serial

REPO_MANIFEST = json.loads((Path(__file__).resolve().parent.parent / "manifest.json").read_text())

MANIFEST = {
    "driver": "venus",
    "product": "Test product",
    "source": "Test source",
    "publishes": ["battery", "solar", "charger"],
    "manufacturer": "Acme",
    "homepage": "https://example.com/driver",
}


def write_manifest(tmp_path: Path, data: dict = MANIFEST) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    return path


def test_info_carries_manifest_fields_and_stamped_version(tmp_path: Path) -> None:
    info = json.loads(build_info("v1.2.3", None, write_manifest(tmp_path)))
    assert info == {**MANIFEST, "version": "v1.2.3"}


def test_unset_version_reports_dev(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path)
    assert json.loads(build_info(None, None, manifest))["version"] == "dev"
    assert json.loads(build_info("", None, manifest))["version"] == "dev"


def write_cpuinfo(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "cpuinfo"
    path.write_text(text)
    return path


PI_CPUINFO = (
    "processor\t: 0\n"
    "model name\t: ARMv7 Processor rev 4 (v7l)\n"
    "Hardware\t: BCM2835\n"
    "Revision\t: a02082\n"
    "Serial\t\t: 00000000a1b2c3d4\n"
    "Model\t\t: Raspberry Pi 3 Model B Rev 1.2\n"
)


def test_board_serial_is_the_serial_line_of_cpuinfo(tmp_path: Path) -> None:
    assert read_board_serial(write_cpuinfo(tmp_path, PI_CPUINFO)) == "00000000a1b2c3d4"


def test_board_serial_omitted_when_unavailable(tmp_path: Path) -> None:
    no_serial = "processor\t: 0\nmodel name\t: x86\n"
    empty = "processor\t: 0\nSerial\t\t: \n"
    all_zero = "processor\t: 0\nSerial\t\t: 0000000000000000\n"
    for text in (no_serial, empty, all_zero):
        assert read_board_serial(write_cpuinfo(tmp_path, text)) is None
    assert read_board_serial(tmp_path / "does-not-exist") is None


def test_unavailable_serial_is_absent_from_info_not_a_placeholder(tmp_path: Path) -> None:
    info = json.loads(
        build_info("v1", read_board_serial(tmp_path / "nope"), write_manifest(tmp_path))
    )
    assert "board_serial" not in info


def test_available_serial_is_published_as_is(tmp_path: Path) -> None:
    serial = read_board_serial(write_cpuinfo(tmp_path, PI_CPUINFO))
    info = json.loads(build_info("v1", serial, write_manifest(tmp_path)))
    assert info["board_serial"] == "00000000a1b2c3d4"


def test_default_manifest_is_the_repo_root_file_in_a_checkout() -> None:
    info = json.loads(build_info("v1", None))
    assert info == {**REPO_MANIFEST, "version": "v1"}


def test_repo_manifest_describes_the_venus_driver() -> None:
    assert REPO_MANIFEST["driver"] == "venus"
    assert REPO_MANIFEST["publishes"] == ["battery", "solar", "charger"]
    assert "version" not in REPO_MANIFEST
    assert "board_serial" not in REPO_MANIFEST


def test_manifest_beside_the_module_wins_over_the_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beside = write_manifest(tmp_path, {**MANIFEST, "product": "Image copy"})
    root_dir = tmp_path / "root"
    root_dir.mkdir()
    root = root_dir / "manifest.json"
    root.write_text(json.dumps({**MANIFEST, "product": "Repo root"}))

    monkeypatch.setattr(driver_info, "MANIFEST_PATHS", (beside, root))
    assert json.loads(build_info("v1", None))["product"] == "Image copy"

    beside.unlink()  # a checkout run has no copy beside the module
    assert json.loads(build_info("v1", None))["product"] == "Repo root"


def test_load_driver_info_stamps_version_from_driver_version_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for env, expected in (("v4.5.6", "v4.5.6"), (None, "dev"), ("", "dev")):
        if env is None:
            monkeypatch.delenv("DRIVER_VERSION", raising=False)
        else:
            monkeypatch.setenv("DRIVER_VERSION", env)
        assert json.loads(load_driver_info())["version"] == expected


def test_load_driver_info_reads_the_board_serial_from_cpuinfo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(driver_info, "CPUINFO_PATH", write_cpuinfo(tmp_path, PI_CPUINFO))
    assert json.loads(load_driver_info())["board_serial"] == "00000000a1b2c3d4"
