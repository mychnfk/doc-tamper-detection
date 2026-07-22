#!/usr/bin/env bash
# start.sh — 一键启动（环境检查 + 起服务；warmup 在 app.py 内完成）
set -e
cd "$(dirname "$0")"
[ -f .env ] || { echo "缺少 .env（需 DASHSCOPE_API_KEY）"; exit 1; }
grep -q DASHSCOPE_API_KEY .env || { echo ".env 缺少 DASHSCOPE_API_KEY"; exit 1; }
[ -f TruFor/TruFor_train_test/pretrained_models/trufor.pth.tar ] || { echo "缺少 TruFor 权重"; exit 1; }
echo "启动 DocGuard（http://localhost:7860 ，浏览器请带 ?__theme=light）"
exec .venv/bin/python app.py
