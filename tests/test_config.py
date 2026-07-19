import importlib
import config


def test_defaults():
    assert config.MAX_SIZE == 1792
    assert config.AGENT_MAX_TURNS == 3
    assert config.ENABLE_HIFI == "auto"
    assert 0 < config.LOW_THRESH < config.HIGH_THRESH < 1


def test_env_override(monkeypatch):
    monkeypatch.setenv("DOCGUARD_MAX_SIZE", "2560")
    monkeypatch.setenv("DOCGUARD_ENABLE_HIFI", "on")
    importlib.reload(config)
    assert config.MAX_SIZE == 2560
    assert config.ENABLE_HIFI == "on"
    monkeypatch.delenv("DOCGUARD_MAX_SIZE")
    monkeypatch.delenv("DOCGUARD_ENABLE_HIFI")
    importlib.reload(config)
