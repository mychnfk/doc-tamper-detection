from evaluate import sweep, suggest_thresholds, verdict_to_bin


def _rows():
    normals = [{"score": s, "label": 0} for s in (0.05, 0.12, 0.2, 0.31)]
    tampers = [{"score": s, "label": 1} for s in (0.45, 0.6, 0.72, 0.88, 0.93)]
    return normals + tampers


def test_sweep_monotonic_ends():
    table = sweep(_rows())
    assert table[0]["thresh"] == 0.0 and table[0]["tpr"] == 1.0 and table[0]["fpr"] == 1.0
    assert table[-1]["tpr"] == 0.0 and table[-1]["fpr"] == 0.0


def test_suggest_thresholds_separates():
    low, high = suggest_thresholds(_rows())
    assert 0.31 < low < high < 0.72      # low 高于全部 normal，high 落在篡改分布下沿（P30≈0.62）


def test_verdict_to_bin():
    assert verdict_to_bin("高度可疑") == 1
    assert verdict_to_bin("疑似篡改") == 1
    assert verdict_to_bin("正常") == 0
    assert verdict_to_bin("无法审核(非金融单据)") is None
