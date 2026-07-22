import sys
import types

from evaluate import CATEGORIES, run_batch, sweep, suggest_thresholds, verdict_to_bin


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


def test_run_batch_empty_dataset_no_csv(tmp_path, monkeypatch):
    fake = types.ModuleType("run_inference")           # 不加载真模型/torch
    fake.select_device = lambda: "cpu"
    fake.load_model = lambda device, path: None
    fake.run_single = lambda *a, **k: None
    fake.TRUFOR_ROOT = str(tmp_path)
    monkeypatch.setitem(sys.modules, "run_inference", fake)
    for cat in CATEGORIES:
        (tmp_path / "eval-images" / cat).mkdir(parents=True)
    monkeypatch.chdir(tmp_path)                        # collect_dataset 默认 root 相对 CWD

    out = tmp_path / "results.csv"
    run_batch("cv", str(out))                          # 空数据集应友好返回而非 IndexError
    assert not out.exists()                            # 且不写 CSV
