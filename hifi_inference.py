# hifi_inference.py — HiFi-Net（CHELSEA234/HiFi_IFDL，CVPR23）第二意见适配器
# 双轨可用性：本文件在任何环境下都可安全 import；hifi_available() 探测真实的权重/依赖/
# 硬件前提，探测不过直接返回 False（真实原因，非硬编码）——tools.py::SecondOpinionTool
# 依赖这个真实探测决定是否把 second_opinion 注册进工具箱。
#
# 与 TruFor（run_inference.py）的关键差异（Mac 实测，详见 docs/dev-log.md Task 11）：
# 1. 固定预处理尺寸——上游 HiFi_Net._transform_image() 把输入统一 resize 到 256x256
#    (bicubic) 再推理，不像 TruFor 那样按原图/切片走近原分辨率。这是 HiFi-Net 自己的
#    内部契约（同坑 #2 的免责条款）：它的 score/map 是"256x256 缩略图级"证据，精细度
#    与 TruFor 的"全图/切片级"证据不可直接比较，仅作独立的第二意见参考。
# 2. localize() 返回二值 mask（阈值化于超球体距离 2.3），不是连续概率热力图。
# 3. 上游源码在模型定义与工具函数里多处硬编码 cuda：
#      - models/NLCDetection_api.py::NLCDetection.__init__ 直接 .cuda() 两个 split tensor
#      - HiFi_Net.py::HiFi_Net.__init__ 硬编码 torch.device('cuda:0') + nn.DataParallel
#      - utils/utils.py 模块级 `device = torch.device('cuda:0')`，
#        restore_weight_helper() 硬编码 map_location='cuda:0'
#    这些硬编码在模型定义层，不是简单的"忘记传 device 参数"，无法在不 fork 上游源码的
#    前提下让它们跑在 MPS/CPU 上——这是 HiFi-Net 自身的内部契约（同坑 #2 免责），本适配器
#    如实地把"需要 CUDA"当作 hifi_available() 的一个真实前提，而非本适配器的 bug。
#    服务器（16G VRAM，真实 CUDA）天然满足这一契约，Mac（MPS/CPU）天然不满足。
import os
import sys

import numpy as np
import torch

import config

_HERE = os.path.dirname(__file__)
_HIFI_REPO_DIR = os.path.join(_HERE, "HiFi_IFDL")   # git clone https://github.com/CHELSEA234/HiFi_IFDL（gitignored，同 TruFor/ 先例）
_WEIGHTS_DIR = os.path.join(_HERE, "hifi_weights")  # 本项目统一存放权重的位置（gitignored）
# 文件名/子目录名来自上游 utils/utils.py::restore_weight_helper 的实际调用参数
# （restore_weight_helper(FENet, "weights/HRNet", 750001) 等），非猜测。
_HRNET_CKPT = os.path.join(_WEIGHTS_DIR, "HRNet", "750001.pth")
_NLC_CKPT = os.path.join(_WEIGHTS_DIR, "NLCDetection", "750001.pth")

_model = None


def _weights_ready():
    return os.path.isfile(_HRNET_CKPT) and os.path.isfile(_NLC_CKPT)


def _wire_repo_path():
    if _HIFI_REPO_DIR not in sys.path:
        sys.path.insert(0, _HIFI_REPO_DIR)


def hifi_available():
    """权重 + 依赖 + 硬件前提探测，不加载模型。任一缺失即 False，且都是真实原因：
    - 权重：hifi_weights/HRNet/750001.pth 与 hifi_weights/NLCDetection/750001.pth
      （下载方式见 docs/dev-log.md Task 11：仅有 Google Drive 文件夹链接，无法脚本化下载）
    - 仓库：HiFi_IFDL/ 需存在（git clone 官方仓库到此路径）
    - 硬件：torch.cuda.is_available()——上游源码硬编码 cuda，见模块 docstring 第 3 点
    - 依赖：kmeans_pytorch / einops / scikit-learn / imageio 需可 import
      （HiFi_Net.py 经 utils/utils.py 无条件引入，即使只做推理也绕不开）
    """
    if not _weights_ready():
        return False
    if not os.path.isdir(_HIFI_REPO_DIR):
        return False
    if not torch.cuda.is_available():
        return False
    try:
        _wire_repo_path()
        import importlib
        importlib.import_module("HiFi_Net")
        return True
    except ImportError:
        return False


def _ensure_weights_symlink():
    """上游 restore_weight_helper() 用仓库相对路径 "weights/HRNet" 等硬编码定位权重，
    因此把本项目 hifi_weights/ 下的对应子目录软链进仓库自己的 weights/，桥接两边约定；
    避免复制权重文件。"""
    os.makedirs("weights", exist_ok=True)
    for name in ("HRNet", "NLCDetection"):
        link = os.path.join("weights", name)
        target = os.path.join(_WEIGHTS_DIR, name)
        if os.path.islink(link) or os.path.exists(link):
            continue
        os.symlink(target, link)


def _load():
    """按上游 HiFi_Net.py 的真实用法加载（README quick-start：HiFi_Net()/.detect()/.localize()）。
    设备遵循上游硬编码 cuda:0（config.DEVICE_OVERRIDE 在此不生效，见模块 docstring 第 3 点）。
    需 chdir 到仓库根目录，因为上游权重加载用的是仓库相对路径（同 run_inference.py::load_model
    对 TruFor 的处理方式）。"""
    global _model
    if _model is not None:
        return _model

    if not _weights_ready():
        # 权重未就绪时提前报错并退出，避免在仓库目录里留下悬空软链（ENABLE_HIFI=on 会
        # 绕过 hifi_available() 强制走到这里，见 tools.py::SecondOpinionTool.available）。
        raise FileNotFoundError(
            f"HiFi-Net 权重未就绪：{_HRNET_CKPT} / {_NLC_CKPT} 需存在（见 docs/dev-log.md Task 11）")
    if not os.path.isdir(_HIFI_REPO_DIR):
        raise FileNotFoundError(f"HiFi-Net 仓库未就绪：{_HIFI_REPO_DIR} 需存在（git clone 官方仓库）")

    _wire_repo_path()
    orig_cwd = os.getcwd()
    os.chdir(_HIFI_REPO_DIR)
    try:
        _ensure_weights_symlink()
        from HiFi_Net import HiFi_Net
        _model = HiFi_Net()
    finally:
        os.chdir(orig_cwd)
    return _model


def run_hifi(image_path):
    """DetectorBackend 形状，镜像 run_inference.py 的返回结构。
    score：HiFi.detect() 的 prob，上游已归一到 [0,1]（README 示例即 0-1 浮点，无需 /255）。
    map：HiFi.localize() 的二值 mask（0/1，非连续概率图——见模块 docstring 第 2 点）。
    infer_size：固定 256x256（上游内部 resize，见模块 docstring 第 1 点），标注
    "(hifi fixed-size)" 以区分 TruFor 的原图/切片尺寸标注。
    image_path 需为绝对路径或相对当前工作目录路径——_load() 内部会临时 chdir 到仓库
    目录，此函数在 chdir 之外调用 detect/localize，故用调用时的 CWD 解析相对路径。
    """
    m = _load()
    image_path = os.path.abspath(image_path)
    _, prob = m.detect(image_path)
    mask = np.asarray(m.localize(image_path), dtype=np.float32)
    h, w = mask.shape
    return {"score": float(prob), "map": mask, "conf": None,
            "infer_size": f"{w}x{h} (hifi fixed-size)"}


def render_hifi_heatmap(result):
    from PIL import Image
    import matplotlib
    matplotlib.use("agg")
    import matplotlib.cm as cm
    return Image.fromarray((cm.RdBu_r(result["map"])[:, :, :3] * 255).astype("uint8"))
