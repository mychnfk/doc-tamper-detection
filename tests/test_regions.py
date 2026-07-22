import numpy as np
from regions import extract_candidate_regions


def _map_with_blocks():
    m = np.zeros((200, 400), dtype=np.float32)
    m[20:60, 40:120] = 0.9    # 大块高分
    m[150:170, 300:340] = 0.6  # 小块中分
    m[0:2, 0:2] = 0.8          # 面积过滤应剔除 (4/80000 < 0.0005×... 视阈值)
    return m


def test_extract_basic():
    regs = extract_candidate_regions(_map_with_blocks(), thresh=0.5, top_k=5, min_area_frac=0.001)
    assert len(regs) == 2
    assert regs[0]["mean_score"] > regs[1]["mean_score"]          # 降序
    assert regs[0]["id"] == 1 and regs[1]["id"] == 2
    x1, y1, x2, y2 = regs[0]["bbox"]
    assert 0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000
    assert abs(x1 - 100) <= 15 and abs(x2 - 300) <= 15            # 40/400,120/400 → 100,300


def test_empty_map():
    assert extract_candidate_regions(np.zeros((100, 100), dtype=np.float32)) == []


def test_top_k():
    m = np.zeros((100, 1000), dtype=np.float32)
    for i in range(8):
        m[10:40, i * 120 + 10: i * 120 + 60] = 0.5 + i * 0.05
    regs = extract_candidate_regions(m, thresh=0.4, top_k=3, min_area_frac=0.0001)
    assert len(regs) == 3
