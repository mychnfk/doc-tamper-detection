import run_inference


def test_resolve_max_size_defaults_to_config_not_hardcoded(monkeypatch):
    monkeypatch.setattr(run_inference.docguard_config, "MAX_SIZE", 512)
    assert run_inference._resolve_max_size(None) == 512   # 未传参时跟随 config，而非硬编码 1792
    assert run_inference._resolve_max_size(999) == 999     # 显式传参仍可覆盖
