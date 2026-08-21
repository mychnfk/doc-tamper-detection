#!/usr/bin/env bash
# build-fonts.sh — 自托管字体：下载 → 子集化 → 落到 web/public/fonts/
#
# 为什么不用 CDN：演示机可能无外网（spec §5 禁令）。字体必须随仓库走。
# 为什么用 curl 而不是 npm：Node 的 fetch 不走系统代理（本项目坑 #9），curl 走。
#
# 中文子集范围＝GB2312 全集（6763 字），不是「界面文案字符集」——
# 因为 VLM 的审核结论是动态中文，只子集界面文案会让结论区掉回系统字体，
# 同一页出现两种字形。GB2312 覆盖现代简体中文实际用字，兜底仍挂系统中文。
#
# 用法: web/scripts/build-fonts.sh   （幂等；字体已存在则跳过下载）
set -e
cd "$(dirname "$0")/../.."

OUT=web/public/fonts
WORK=/tmp/docguard-fonts
PY=.venv/bin/python
SUBSET=.venv/bin/pyftsubset

mkdir -p "$OUT" "$WORK"

# ─── 1. HarmonyOS Sans SC（华为，免费商用）───────────────────────────
HOS_ZIP="$WORK/HarmonyOS_Sans.zip"
if [ ! -f "$WORK/HarmonyOS_Sans_SC_Regular.ttf" ]; then
  echo "下载 HarmonyOS Sans（约 50MB）…"
  curl -sSL --max-time 300 -o "$HOS_ZIP" \
    "https://cdn.jsdelivr.net/npm/harmonyos-sans@1.0.0/HarmonyOS%20Sans.zip"
  unzip -o -j "$HOS_ZIP" "HarmonyOS Sans/HarmonyOS_Sans_SC/HarmonyOS_Sans_SC_Regular.ttf" \
    "HarmonyOS Sans/HarmonyOS_Sans_SC/HarmonyOS_Sans_SC_Medium.ttf" \
    "HarmonyOS Sans/HarmonyOS_Sans_SC/HarmonyOS_Sans_SC_Bold.ttf" -d "$WORK" >/dev/null
fi

# ─── 2. 生成子集字符集（GB2312 全集 + ASCII + 中英标点）──────────────
CHARS="$WORK/charset.txt"
"$PY" - "$CHARS" <<'PYEOF'
import sys
chars = set()
# GB2312 全集：遍历双字节区并反解，得到 6763 个汉字 + 682 个符号
for hi in range(0xA1, 0xFF):
    for lo in range(0xA1, 0xFF):
        try:
            chars.add(bytes([hi, lo]).decode("gb2312"))
        except UnicodeDecodeError:
            pass
chars |= set(chr(c) for c in range(0x20, 0x7F))          # ASCII 可见字符
chars |= set("　、。〈〉《》「」『』【】〔〕—…‰′″※→←↑↓№℃")  # 常用中文标点补充
with open(sys.argv[1], "w", encoding="utf-8") as f:
    f.write("".join(sorted(chars)))
print(f"字符集 {len(chars)} 个")
PYEOF

# ─── 3. 子集化三个中文字重 ────────────────────────────────────────────
for w in Regular:400 Medium:500 Bold:700; do
  name="${w%%:*}"; weight="${w##*:}"
  src="$WORK/HarmonyOS_Sans_SC_${name}.ttf"
  dst="$OUT/harmonyos-sans-sc-${weight}.woff2"
  [ -f "$dst" ] && { echo "跳过 $dst（已存在）"; continue; }
  "$SUBSET" "$src" --text-file="$CHARS" --flavor=woff2 \
    --layout-features='*' --output-file="$dst"
  echo "$dst  $(du -h "$dst" | cut -f1)"
done

# ─── 4. IBM Plex Sans / Mono（OFL，拉丁与数字，本就很小，不子集）──────
plex() {   # $1=包名 $2=文件名 $3=输出名
  local dst="$OUT/$3"
  [ -f "$dst" ] && { echo "跳过 $dst（已存在）"; return; }
  curl -sSL --max-time 120 -o "$dst" \
    "https://cdn.jsdelivr.net/npm/@ibm/$1@1.1.0/fonts/complete/woff2/$2"
  echo "$dst  $(du -h "$dst" | cut -f1)"
}
plex plex-sans IBMPlexSans-Regular.woff2  ibm-plex-sans-400.woff2
plex plex-sans IBMPlexSans-Medium.woff2   ibm-plex-sans-500.woff2
plex plex-sans IBMPlexSans-SemiBold.woff2 ibm-plex-sans-600.woff2
plex plex-mono IBMPlexMono-Regular.woff2  ibm-plex-mono-400.woff2

echo
echo "字体总计: $(du -sh "$OUT" | cut -f1)"
ls -la "$OUT"
