"""VLM 通路冒烟：一次最小文本调用，验证 API key 与端点连通。

公司内网可能到不了 DashScope——失败不阻塞部署（系统会自动降级为仅像素取证）。
退出码: 0=通  1=不通
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    if not os.getenv("DASHSCOPE_API_KEY"):
        import config  # noqa: F401 — 触发 load_dotenv 再试一次
        if not os.getenv("DASHSCOPE_API_KEY"):
            print("SKIP: 未配置 DASHSCOPE_API_KEY")
            return 1
    try:
        from agent import call_vlm
        text = call_vlm([{"role": "user", "content": [{"text": "只回复一个字：通"}]}])
        print(f"OK: VLM 响应 -> {text[:50]}")
        return 0
    except Exception as e:  # noqa: BLE001 — 冒烟脚本，任何失败都归为不通
        print(f"FAIL: VLM 不可达 -> {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
