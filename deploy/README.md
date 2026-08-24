# DocGuard 部署说明（给运维，全程约 15-30 分钟，只需 3 步）

## 前提

- Windows 10/11，装有 NVIDIA 显卡驱动（桌面右键有 "NVIDIA 控制面板" 即已装）
- 能上外网（装依赖约 2.5GB 下载；装完之后运行不依赖外网*）

## 部署步骤

1. 把 zip 解压到固定目录（例如 `D:\docguard\`，以后不要移动）
2. **双击 `deploy.bat`**，UAC 弹窗点"是"
3. 首次运行会询问 `DASHSCOPE_API_KEY`：项目组会单独提供；拿不到或内网不通**直接回车跳过**

之后全自动：环境检测 → 装依赖 → 跑测试 → 注册服务并启动。
结束后窗口会显示访问地址（本机 http://localhost:8000）。

## 部署完成后

- 把根目录生成的 **`deploy-report.txt`** 通过丰声发回项目组（无论成功失败）
- 服务已注册为 Windows 服务 `DocGuard`：开机自启、崩溃自动拉起，无需人工值守

## 出问题了？

- **中途失败**：修复报错提示的问题后，再次双击 `deploy.bat` 即可断点续跑（已完成步骤自动跳过）
- **服务操作**：`deploy\nssm.exe restart DocGuard`（重启）/ `stop` / `start`
- **看日志**：`logs\docguard.log`（运行日志）、`logs\docguard.err.log`（报错）
- 其余情况：把 `deploy-report.txt` + `logs\docguard.err.log` 发回项目组即可，不用自己排查

*大模型复核功能需要能访问 DashScope（阿里云）；内网不通时系统自动降级为仅像素取证模式，核心检测功能不受影响。

## 接入公司内部模型服务（可选，替代 DashScope）

若内部模型网关是 OpenAI 兼容接口（绝大多数是）且有**多模态（视觉）模型**，
编辑根目录 `.env` 为如下四行后执行 `deploy\nssm.exe restart DocGuard` 即可，无需改代码：

```
DASHSCOPE_API_KEY=<网关下发的 key>
DOCGUARD_VLM_PROTOCOL=openai
DOCGUARD_VLM_BASE_URL=<网关地址，形如 http://xxx/v1>
DOCGUARD_VLM_MODEL=<网关上的视觉模型名>
```

验证：`.venv\Scripts\python.exe deploy\check_vlm.py` 输出 OK 即通。
