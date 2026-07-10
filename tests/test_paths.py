
from app import paths


def test_source_checkout_uses_repository_root(monkeypatch):
    monkeypatch.delattr(paths.sys, "frozen", raising=False)
    assert paths.data_root() == paths.resource_root()
    assert paths.profiles_file().name == "profiles.json"


def test_switchblade_home_overrides_data_root(monkeypatch, tmp_path):
    target = tmp_path / "custom"
    monkeypatch.setenv("SWITCHBLADE_HOME", str(target))
    assert paths.data_root() == target.resolve()


def test_frozen_build_uses_local_appdata(monkeypatch, tmp_path):
    monkeypatch.delenv("SWITCHBLADE_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    assert paths.data_root() == tmp_path / paths.APP_DIR_NAME


def test_bootstrap_copies_defaults_once(monkeypatch, tmp_path):
    resources = tmp_path / "resources"
    data = tmp_path / "data"
    (resources / "profiles" / "images").mkdir(parents=True)
    (resources / "profiles" / "profiles.json").write_text("{}", encoding="utf-8")
    (resources / "profiles" / "images" / "bg.png").write_bytes(b"first")
    monkeypatch.setattr(paths, "resource_root", lambda: resources)
    monkeypatch.setattr(paths, "data_root", lambda: data)

    destination = paths.bootstrap_user_data()
    assert destination.read_text(encoding="utf-8") == "{}"
    assert (data / "profiles" / "images" / "bg.png").read_bytes() == b"first"

    destination.write_text("changed", encoding="utf-8")
    (resources / "profiles" / "images" / "bg.png").write_bytes(b"second")
    paths.bootstrap_user_data()
    assert destination.read_text(encoding="utf-8") == "changed"
    assert (data / "profiles" / "images" / "bg.png").read_bytes() == b"first"
