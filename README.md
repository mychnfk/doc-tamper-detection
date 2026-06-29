# DocGuard — AI 驱动的文档真伪审核系统

> 公司内部比赛项目：探索 AI 在财经领域的应用

## 项目简介

金融文档（合同、单据、函件）上传时的篡改检验系统。CV 工具做像素级取证，多模态大模型做独立复核验证，输出财务人员可理解的审核意见。

## 架构

```
query(上传文档图片)
  → tool use: CV 检测工具 (TruFor)
  → VLM 复核验证 (Claude / Qwen-VL API)
  → output: 判定 + 热力图 + 语义化审核意见
```

## 技术栈

- **CV 检测层**: TruFor (CVPR 2023) — Noiseprint++ 噪声指纹取证
- **VLM 复核层**: Claude API / Qwen-VL API — 交叉验证 + 语义解读
- **前端**: Gradio
- **Python**: 3.10+

## 快速开始

```bash
# 克隆项目
git clone https://github.com/zhang/doc-tamper-detection.git
cd doc-tamper-detection

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Mac/Linux
# venv\Scripts\activate   # Windows

# 安装依赖 (待补充)
pip install -r requirements.txt
```

## 项目状态

- [x] 技术调研完成 (详见 `调研记录.md`)
- [ ] TruFor 集成
- [ ] Gradio Demo UI
- [ ] VLM 复核层
- [ ] 测试数据准备

## 文件结构

```
doc-tamper-detection/
├── README.md              # 项目说明
├── 调研记录.md              # 完整技术调研 & 比赛方案
├── .gitignore
└── (待开发)
    ├── app.py             # Gradio 主应用
    ├── detection/         # CV 检测层
    ├── review/            # VLM 复核层
    └── requirements.txt
```
