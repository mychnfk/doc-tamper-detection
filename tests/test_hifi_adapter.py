import pytest
import hifi_inference


def test_available_is_bool():
    assert isinstance(hifi_inference.hifi_available(), bool)


@pytest.mark.skipif(not hifi_inference.hifi_available(), reason="HiFi-Net 未就绪（合法的双轨状态）")
def test_run_hifi_shape():
    r = hifi_inference.run_hifi("example-images/check.jpg")
    assert set(r) >= {"score", "map", "conf", "infer_size"}
    assert 0.0 <= r["score"] <= 1.0
    assert r["map"].ndim == 2
