# config.py — 双轨开关中心：Mac/服务器差异只体现为这里的环境变量
import os
from dotenv import load_dotenv

load_dotenv()

DEVICE_OVERRIDE = os.getenv("DOCGUARD_DEVICE", "")          # "" = 自动选择 cuda>mps>cpu
MAX_SIZE = int(os.getenv("DOCGUARD_MAX_SIZE", "1792"))      # 服务器到位后提档 2560-3072
AGENT_MAX_TURNS = int(os.getenv("DOCGUARD_MAX_TURNS", "3"))
ENABLE_HIFI = os.getenv("DOCGUARD_ENABLE_HIFI", "auto")     # auto|on|off
LOW_THRESH = float(os.getenv("DOCGUARD_LOW_THRESH", "0.4"))   # 评测校准后回写 .env
HIGH_THRESH = float(os.getenv("DOCGUARD_HIGH_THRESH", "0.7"))
VLM_MAX_SIZE = int(os.getenv("DOCGUARD_VLM_MAX_SIZE", "2048"))  # 送 VLM 的图像长边上限，与取证无关
VLM_MODEL = os.getenv("DOCGUARD_VLM_MODEL", "qwen3.7-max-2026-06-08")
VLM_BASE_URL = os.getenv("DOCGUARD_VLM_BASE_URL",
                         "https://llm-grvsxc3jcll56h4b.cn-beijing.maas.aliyuncs.com/api/v1")
