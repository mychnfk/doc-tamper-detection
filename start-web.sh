#!/usr/bin/env bash
# start-web.sh — 新版前端一键启动（Gradio 回退版仍用 ./start.sh，端口 7860）
set -e
cd "$(dirname "$0")"
[ -f .env ] || { echo "缺少 .env（需 DASHSCOPE_API_KEY）"; exit 1; }
grep -qE '^DASHSCOPE_API_KEY=..+' .env || { echo ".env 缺少有效的 DASHSCOPE_API_KEY"; exit 1; }
[ -f TruFor/TruFor_train_test/pretrained_models/trufor.pth.tar ] || { echo "缺少 TruFor 权重"; exit 1; }
command -v node >/dev/null || { echo "缺少 node（需 v20+）"; exit 1; }
[ -d web/dist ] || { echo "前端未构建，正在构建…"; (cd web && npm run build); }
echo "启动 DocGuard Web（http://localhost:8000）"
# -u 不可省：start.sh 缺这个参数导致非交互启动时日志全卡在缓冲区，看不到 Warmup done
exec .venv/bin/python -u -m uvicorn api:app --host 0.0.0.0 --port 8000
