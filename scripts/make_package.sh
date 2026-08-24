#!/usr/bin/env bash
# make_package.sh — 组装 Windows 部署离线包（在 Mac 开发机上运行）
#
# 产物: dist-package/docguard-deploy-<日期>-<rev>.zip + 同名 .sha256
# 内容: git 跟踪代码 + TruFor(剔除 .git 省 128MB) + 预构建前端 + 基线回归图
# 注意: 代码部分取自 git archive HEAD——未提交的改动不会进包，打包前先提交。
# 基线图用 ASCII 文件名——mac 打的 zip 里中文文件名在部分 Windows 解压器下会乱码，
# 功能性文件一律不用中文名（docs/ 里的中文名文档乱码不影响运行，可接受）。
set -e
cd "$(dirname "$0")/.."

REV=$(git rev-parse --short HEAD)
STAGE=dist-package/docguard
OUT="dist-package/docguard-deploy-$(date +%Y%m%d)-${REV}.zip"

echo "── 1/6 前端构建 ──"
(cd web && npm run build | tail -1)

echo "── 2/6 staging 代码（git archive，自动排除 .env/runs/评测图）──"
rm -rf "$STAGE"
mkdir -p "$STAGE"
git archive HEAD | tar -x -C "$STAGE"

echo "── 3/6 TruFor 601MB → 剔除 .git ──"
rsync -a --exclude '.git' TruFor/ "$STAGE/TruFor/"

echo "── 4/6 预构建前端 + 基线图 ──"
rsync -a web/dist/ "$STAGE/web/dist/"
mkdir -p "$STAGE/deploy/baseline"
cp "example-images/微信圖片_20260629180819_55_237.jpg" "$STAGE/deploy/baseline/normal_55_237.jpg"
cp example-images/check.jpg "$STAGE/deploy/baseline/tiled_check.jpg"

echo "── 5/6 版本戳 ──"
{ echo "rev: $REV"; date '+date: %F %T'; git log --oneline -1; } > "$STAGE/VERSION.txt"

echo "── 6/6 打包 ──"
rm -f "$OUT" "$OUT.sha256"
(cd dist-package && zip -rqX "$(basename "$OUT")" docguard -x '*.DS_Store')
shasum -a 256 "$OUT" | tee "$OUT.sha256"
echo
echo "staging: $(du -sh "$STAGE" | cut -f1)   zip: $(du -sh "$OUT" | cut -f1)"
