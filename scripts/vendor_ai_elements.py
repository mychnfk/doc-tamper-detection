# scripts/vendor_ai_elements.py — 从 registry JSON 提取需要的组件源码并打本地补丁
#
# 为什么不用官方 CLI：本机 Node 的 fetch 不读 HTTPS_PROXY，`npx ai-elements` 必 ECONNRESET；
# curl 走代理正常，所以先 curl 下 registry 再本地提取。
#
# 本地补丁必须写在这里而不是手改文件——否则重跑本脚本会被上游原文覆盖。
#
# 用法：curl -s -o /tmp/ai-elements-registry.json https://elements.ai-sdk.dev/api/registry/all.json
#       .venv/bin/python scripts/vendor_ai_elements.py /tmp/ai-elements-registry.json
import json
import pathlib
import sys

# 只取这 3 个。其余 6 个已评估后弃用（2026-08-13）：
#   message/reasoning  → 拖入 streamdown 全家桶（mermaid 流程图 + KaTeX 公式），检测报告用不到
#   reasoning/shimmer  → 依赖 motion，与 spec §5.1 禁令 9「禁装饰动效」冲突
#   tool               → props 绑死 AI SDK 的 ToolUIPart，与自有 TraceEvent 结构不兼容
#   image              → 渲染 base64 data URL，与「图片落盘只传 URL」的架构相反
#   confirmation       → 无用户确认交互场景
WANTED = ["chain-of-thought", "task", "conversation"]
OUT = pathlib.Path("web/src/components/ai-elements")

# conversation.tsx 里只有 ConversationDownload（把对话导出为 md）依赖 AI SDK 的 UIMessage。
# 我们不做对话导出，切掉这一段就能彻底摘掉 `ai` 这个包。
TRIM_FROM = "const getMessageText = (message: UIMessage): string =>"


def patch(stem, src):
    src = src.replace('@/registry/default/ui/', '@/components/ui/')
    if stem == "conversation":
        if TRIM_FROM not in src:
            raise SystemExit(f"conversation.tsx 上游已变更，找不到裁剪锚点：{TRIM_FROM!r}\n"
                             "请重新确认 ConversationDownload 是否仍依赖 `ai`，再更新本脚本。")
        src = src[:src.index(TRIM_FROM)].rstrip() + "\n"
        src = src.replace('import type { UIMessage } from "ai";\n', '')
        src = src.replace('import { ArrowDownIcon, DownloadIcon } from "lucide-react";',
                          'import { ArrowDownIcon } from "lucide-react";')
        if '"ai"' in src:
            raise SystemExit("裁剪后仍残留 `ai` 依赖，请检查上游改动")
    return src


def main(registry_path):
    data = json.loads(pathlib.Path(registry_path).read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for f in data["files"]:
        stem = f["path"].split("/")[-1].replace(".tsx", "")
        if stem in WANTED:
            (OUT / f"{stem}.tsx").write_text(patch(stem, f["content"]), encoding="utf-8")
            written.append(stem)
    missing = sorted(set(WANTED) - set(written))
    print(f"已写入 {len(written)} 个组件到 {OUT}")
    if missing:
        print(f"⚠️ registry 中未找到：{missing}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1])
