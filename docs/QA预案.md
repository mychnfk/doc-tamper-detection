# DocGuard 决赛答辩 QA 预案

> 面向对象：**团队自用**，备战决赛评委（含顺丰科技技术领导）追问。技术深度按真实颗粒度写，不做面向财务用户的简化包装（那是 UI 文案的事，见 `app.py`）。
> 结构：按 `docs/superpowers/specs/2026-07-19-agent-loop-finals-design.md` 第 8 节骨架，四类问题、每题 3-5 句口径 + 指向证据。凡是依赖评测集实跑数字、目前还没有的部分，用 `【待填：...】` 标出并给出人工产出该数字的确切命令/位置，不用编造的数字充数。
> 通用应对姿态：被问"给我看看"时，直接翻到本文标注的文件/函数/行号，或复跑标注的命令。

---

## 一、架构类

### Q1. 为什么是"CV 检测 + VLM 复核"两层架构，而不是端到端一个模型？

纯 CV 模型只有像素级证据、不理解内容——分不清标红的地方写的是金额还是水印；纯 VLM 有语义理解力，但没有像素级取证能力，看不出压缩痕迹/噪声不一致这类肉眼不可见的线索。这组对比写在 `调研记录.md` 第 104-106 行（"为什么 CV+VLM 交叉验证 > 任一单独使用"），不是临时想的说辞。分层还有工程理由：`DetectorBackend` 统一成 `run(image_path) → {score, map, conf, infer_size}` 这一个形状（spec 第 70-71 行），TruFor 和 HiFi-Net 可以互换/并存而不动上层协议，VLM 那一层换供应商也不用动 CV 代码；打包成一个端到端模型就没有这种可插拔性了。更现实的一点：我们既没有"篡改类型 + 财务语义"联合标注的数据集，也没有训练这种端到端模型的时间（决赛升级总预算两周多的业余时间），分层等于直接复用 TruFor 和 Qwen-VL 两个已经训练好的能力，而不是从零训练。

### Q2. Agent Loop 怎么保证不会死循环/失控？

三重终止，`agent.py::_agent_loop` 里都能直接读到：① VLM 自己判断证据充分，输出 `decision:"verdict"` 正常结束（`source="agent"`）；② 到达 `config.AGENT_MAX_TURNS`（默认 3 轮）VLM 还没主动 verdict，代码会在下一轮消息里强制插入"请立即输出 decision=verdict 的最终判定"（第 201-204 行），这一轮不论 VLM 想不想继续 investigate 都会被摘取 verdict 字段强行收敛（`source="agent-forced"`）；③ JSON 连续解析失败 2 次（`parse_fails >= 2`，第 210-214 行）会向上抛 `ProtocolError`，由 `review()` 统一捕获后整体降级到直链模式，直链再失败还有第三级 CV-only 兜底。"不管走哪条路，最后一个事件必为 verdict" 这条不变量有专门的回归测试覆盖：`tests/test_agent_loop.py` 11 个测试函数覆盖 VLM 网络异常直接抛出、瞬时抖动后重试成功、连续解析失败、工具执行异常（含裸抛 TypeError）、强制轮遇到非法 verdict 字段形状、direct 模式自身失败等场景（`.superpowers/sdd/progress.md` 里 Task 6 词条记的"6 路对抗验证"），每一个都断言 `evs[-1].type == "verdict"`。这条终止链不是纸面设计——`docs/dev-log.md` Task 7 Step 3b 记录过一次 prompt 实验让 `50_237.jpg` 真机跑到 4 轮耗尽、真实触发强制收敛（`source=agent-forced`），证明这条路径在真实条件下确实会生效，不是只有单测在跑。

### Q3. 协议层为什么用自管 JSON 协议，而不用大模型原生 Function Calling？

探测过，而且结论是**明确支持**——`scripts/probe_fc.py`（`docs/dev-log.md` Task 1 Step 4）用专属端点 `qwen3.7-max-2026-06-08` 实测，返回的 `tool_calls` 字段非空，拿到结构合法的 `zoom_region` 调用（`{"bbox":[250,250,750,750]}`，落在 0-1000 归一化范围内，`arguments` 可解析），这不是"能力不够才退而求其次"，是探测之后的主动选择。选择自管 JSON 协议的原因有两条：第一，轨迹要逐事件流式推给 UI（`TraceEvent` 生成器），自己解析 JSON 块比原生 FC 的工具调用生命周期（由 SDK 内部管理）更灵活可控；第二，失败回退路径要完全在自己手里——"JSON 连续解析失败 2 次触发降级"这套语义是我们自己定义的，换成原生 FC 的话，失败模式和重试语义要看 SDK/API 自己怎么定义。探测结论与"仍选 JSON 协议"的决策原因都写在 `docs/dev-log.md` Task 1 与 spec 决策表"协议"一行，QA 口径可以直接说：探测过、支持、但为轨迹流式化与回退可控主动选择自管协议——这是工程判断，不是回避问题。

### Q4. 以后要加新工具（比如 OCR、别的检测模型），要改几处代码？

工具契约在 `tools.py::Tool` 基类定死四个成员：`name`/`description`/`args_hint`（这三项直接拼进发给 VLM 的 system prompt——`agent.py::build_system_prompt` 第 79-80 行 `tool_lines` 是从传入的 `tools` 列表动态生成的）、`available()`（环境探测）、`run(ctx, **kwargs)`（执行）。注册表 `build_registry()`（tools.py 第 87-88 行）启动时把每个工具实例过一遍 `available()`，只留下返回 `True` 的——现在 `SecondOpinionTool.available()` 会分层检查 `config.ENABLE_HIFI` 开关、`hifi_inference` 模块能否 import、`hifi_available()` 的真实探测结果（权重文件/CUDA 是否就绪），这就是为什么 `build_registry()` 在 Mac 上实测只返回 `['zoom_region']`（`tests/test_tools.py::test_registry_excludes_unavailable`），服务器 CUDA + 权重就位后同一份代码自动多出 `second_opinion`，不用改一行 `agent.py`。以后加新工具只需要写一个新的 `Tool` 子类塞进 `build_registry()` 的元组，协议层和 prompt 模板完全不用动——这是"工具箱随环境伸缩，Agent 协议不变"这条设计原则（spec 第 3 节"Tool"契约那一条，第 73 行）的字面体现。

---

## 二、CV 类

### Q5. TruFor 的"双分支"具体指什么，输出是什么？

TruFor 官方仓库自己的描述（`TruFor/README.md`"Overview"节）：用一个 transformer 融合架构把 RGB 图像的高层特征和一个"学出来的噪声敏感指纹"（Noiseprint++）结合起来，后者只在真实图片上做自监督训练，学的是相机内部/外部处理留下的痕迹，篡改被建模为"偏离每张原图应有的规律噪声模式"。输出是三件套：像素级定位图（localization map）、整图完整性分数（integrity score）、以及一个"可靠性图"（reliability map，标出哪些区域的定位预测容易出错，用来降低误报）。这不是我们复述的宣传语，代码里能直接对上：`run_inference.py::_infer_tile`/`run_single` 里 `pred, conf, det, npp = model(...)` 一行同时拿到定位图（`pred` → softmax 后的 `loc_map`）、可靠性图（`conf`）、整图分数（`det` → sigmoid 后的 `score`）、以及 Noiseprint++ 本身（`npp`）四个输出，和官方描述的三件套（+ 底层噪声图）完全对应。TruFor 在 CASIAv1 公开基准上的指标是 F1=0.789、AUC=0.946（`调研记录.md` 第 307 行）——这是它论文自己报的通用图像篡改基准表现，不是我们自己测的，回答时要说清楚这一点，不要混淆成我们的评测数字。附带一句：TruFor 当前license 是"仅限科研/非商用"（`TruFor/README.md` License 节），如果被问到商用落地路径，这是需要提前想清楚的点。

### Q6. 为什么裁片/送检图片"绝不能缩放"？

这是坑排查阶段（早于本次决赛任务序列）就写进代码铁律的一条：TruFor 的核心信号 Noiseprint++ 是从真实相机噪声学出来的高频指纹，实测过一次影响——图像仅缩小 23%（1080px→830px）就让同一张图的篡改检出分数从 0.945 掉到 0.177，因为 LANCZOS 之类的重采样会把相邻像素的噪声模式混合在一起，直接抹掉这个高频信号。这条"坑 #2 铁律"被写进 `docs/superpowers/plans/2026-07-19-agent-loop-finals-design.md` 的 Global Constraints 第 14 行与 spec 第 162 行，现在代码里严格执行：`run_inference.py::run_single`/`run_tiled` 从不对送入 TruFor 的图像做任何 resize（超过 `MAX_SIZE` 时走切片而不是缩放）；`tools.py::ZoomRegionTool` 放大裁片时也强调"从原始文件按全分辨率裁出"（第 28 行 description）；唯一允许的尺寸上限 `VLM_MAX=2048`（第 32 行，赋值与注释同行——"仅约束送 VLM 的裁片，与取证无关"）只作用于送给 VLM 看的裁片，送检测模型的证据图从不经过这行代码。`tests/test_tools.py::test_zoom_caps_at_2048` 验证的正是"裁片会被限到 2048"这件事，而不是"检测输入会被缩放"。

### Q7. 大图切片推理有什么已知局限？怎么应对？

MPS 统一内存下，SegFormer-B2 的 self-attention 在 2048px 输入附近就会 OOM，所以当前 `MAX_SIZE` 定为 1792px（`config.py` 默认值），超过此尺寸的图片走 `run_inference.py::run_tiled()`（1024px tile、256px overlap、线性淡出权重拼接，见 `_make_blend_weights`）。局限：Noiseprint++ 需要整张图的噪声基线来判断"哪里不对劲"，切片推理只有局部基线，大图的检出力会比整图直推弱——这正是为什么架构上明确"不做"TruFor 裁片重检（spec 第 25 行："Noiseprint++ 需全图噪声基线（已知坑 #3），裁片重检分数不可信"）。三层对策：① `MAX_SIZE` 服务器到位后提档（附录服务器轨清单第 3 条，拟测 2048→2560→3072，用 `50_237.jpg` 验证坑 #3 是否被整图推理终结，结果记入 dev-log）；② `agent.py::build_first_user_content` 给 VLM 一句软提示（`tiled_note`，"全局分数可信度较低，建议对关键区域放大查证"），引导它主动 investigate 而不是照单全收 CV 的低分结论；③ VLM 自己有 `zoom_region` 工具可以对关键区域单独放大细看笔画/印章纹理，弥补 CV 证据力不足。真实案例（`docs/dev-log.md` Task 7）：`50_237.jpg`（3456×4107，切片 30 tiles）CV 首检只给 0.2536 的低分，但 Agent 在 `tiled_note` 引导下主动放大查证印章区和填写区，最终判定"高度可疑/高"（抓住了无盖章签字 + 申请方与收款方名称不一致两个真实红旗），耗时 3:19.49。

### Q8. HiFi-Net 第二意见现在是什么状态？和 TruFor 什么关系？

设计上是第二个独立检测模型：TruFor 靠相机噪声指纹在原图/切片分辨率上工作，HiFi-Net 走完全不同的技术路线（`hifi_inference.py` 里对接的上游 API 是超球体距离阈值判定 + 二值 mask），两个原理不同的模型对同一张图独立给出一致结论时可信度能互相印证，不一致时可以交给 Agent 进一步查证。现状必须如实说明：HiFi-Net 在本机（Mac/MPS）**不可行**——上游 `HiFi_IFDL/models/NLCDetection_api.py` 第 205-206 行把 `.cuda()` 硬编码进模型定义本身，与有没有权重无关，Mac 的 MPS 后端会直接 `AssertionError: Torch not compiled with CUDA enabled`（`docs/dev-log.md` Task 11）。适配器 `hifi_inference.py` 已经按真实上游 API 写好并做了分层真实探测（`hifi_available()`：权重文件→仓库目录→CUDA→依赖），`tools.build_registry()` 在 Mac 上实测只返回 `['zoom_region']`，服务器有真实 CUDA 后按 `ENABLE_HIFI=auto` 的设计零代码自动升级（不需要碰 `.env`）。另一个必须如实告知的局限：HiFi-Net 的 `_transform_image()` 把任何输入都强制 resize 到 256×256（bicubic）才送进网络——这是它自己训练时定死的输入尺寸，不是算力问题，财务单据上的小字/印章细节缩到 256×256 基本丢失，"第二意见"的参考价值可能有限（`docs/dev-log.md` Task 11 明确记录，要求 Task 12 QA 如实说明，不能只展示分数）。两模型的一致率/互补统计（TruFor 漏检中 HiFi 检出数等）要服务器跑通评测集后才有数字——【待填：见附录"服务器轨"部分，命令为 brief 附录第 7 条：对 `collect_dataset()` 逐张跑 `run_hifi()` 落 CSV，与 TruFor 分数并排统计一致率】。

### Q9. CV 检测的误报主要来自哪里？系统怎么处理？

CV 层的误报主要来自和"篡改痕迹"长得像但其实是干净背景噪声的东西：纸张纹理/褶皱、光照不均导致的阴影、水印、低画质压缩噪点，这些都会在 `regions.py::extract_candidate_regions`（阈值 0.5）的连通域提取里冒出高分候选区。系统靠 VLM 复核过滤：VLM 拿到 CV 标出的候选框和原图去交叉验证"这块真的异常吗"。真实案例（`docs/dev-log.md` Task 7，`check.jpg`）：CV 标出的候选区域 `region_id=1`（区域均分 0.6328，候选框级别的灰区）被 Agent 放大后核实为"纸张噪点误报"，但同一次复核里 Agent 另外发现了真正的问题——银行账号用科学计数法表示、且无签章。这个例子同时展示了"排除 CV 误报"和"VLM 独立补充语义线索"两种价值，不是单纯"照单全收 CV 结论"或者"完全不信 CV"，这一发现在原始 prompt（Task 7 Step 2）与最终 prompt（Step 4）两版复跑里一致存在。

---

## 三、指标类

### Q10. 自建评测集的检出率/误报率数字怎么解读？

【待填：评测集跑分后】这一题的数字要等 `eval-images/` 里的真实业务样张到位、`evaluate.py` 实跑完才能填——目前 `eval-images/` 六个子目录只有 `README.md` 和 `.gitkeep` 占位（Task 9 脚手架状态），没有一张真实图片；`evaluate.py --mode cv` 已经用真实 TruFor checkpoint 实测过一次，因为数据集是空的，`collect_dataset()` 返回 `[]`，`run_batch` 会打印"未在 eval-images/ 下找到任何图片"后直接返回（`evaluate.py::run_batch` 空数据集 guard，`tests/test_evaluate.py::test_run_batch_empty_dataset_no_csv` 已覆盖），不是假设行为。数字到位后按这个顺序产出：
```bash
.venv/bin/python evaluate.py --mode cv --out eval-report/results_cv.csv       # 各类别检出率/误报率
.venv/bin/python evaluate.py --calibrate eval-report/results_cv.csv          # 分布图+阈值扫描表+建议阈值
# 人工确认建议阈值、回写 .env 的 DOCGUARD_LOW_THRESH/DOCGUARD_HIGH_THRESH 后：
.venv/bin/python evaluate.py --mode agent --out eval-report/results_agent.csv # CV 单独 vs 完整 Agent 链路对照
```
命令与产出路径见 `.superpowers/sdd/task-10-report.md`"部署/deferred"章节；跑完后按该报告的既定流程把摘要写入 `docs/dev-log.md` 并单独 commit。回答这一题前要先讲清楚口径：图级检出率/误报率为主，不做像素级定位 F1（需要 mask 标注，两周时间做是伪严谨，spec 第 134 行已经把这句话写进设计文档，属于提前主动声明的范围限定，不是被问到才想起来）。

### Q11. 13-15 张的小样本，这个可信度够吗？

13-15 张不是一个能算出置信区间的样本量，这一点要主动承认，不要绕。但"小样本校准阈值"这个方法论不是我们自己想当然——`调研记录.md` 第 301/362 行记录的 DOCFORGE-BENCH（2026 年论文，首个零样本文档伪造评测基准）发现"仅 10 张域内图校准阈值就能把 F1 找回 39%-55%"，我们 `evaluate.py::suggest_thresholds()`（Task 10）做的事情结构上和它一样：不是拿 13-15 张图去证明"我们的 AUC 是多少"，而是拿这批域内图的分数分布去校准 `LOW_THRESH`/`HIGH_THRESH` 这两个决策阈值——这是"点估计校准"，不是"统计意义上的性能验证"，回答时要把这两件事分开说。TruFor 自己在 CASIAv1 上的公开指标（F1=0.789，AUC=0.946，`调研记录.md` 第 307 行）是它论文里的通用图像篡改基准表现，不能直接套到"手机拍照金融单据"这个具体场景，这也是为什么要专门建自己的评测集而不是直接引用论文数字。

### Q12. 系统的能力边界在哪？会不会被专门设计的篡改绕过？

系统定位是"审核辅助"，不是"自动裁决"：每条 verdict 都带一个 `advice` 字段（`agent.py::format_verdict` 渲染成"建议操作"），CV-only 兜底文案也写明"建议结合人工审核"（`_cv_only_verdict`），UI 上没有任何自动阻断/自动拒付动作，财务人员始终是最终决策者——这是"AI 辅助人工而非替代"在代码层面的直接体现，不是一句公关话术。能力边界方面要诚实：一方面，评测集样本量小（见 Q11），不能宣称对"专门针对本系统设计的对抗性伪造"有防御力，比如刻意模拟正常相机噪声的高质量伪造，这类样本我们没有专门测试过；另一方面，`conclusion` 与 `risk` 字段偶尔会出现语义不一致（`docs/dev-log.md` Task 7 记录的 8 次真机复跑里出现 1 次，`50_237.jpg` 一次输出 `conclusion=正常` 但 `risk=高、advice=拒付`），样本太小还不足以判断是偶发噪音还是系统性问题，留给评测集扩大后再评估——这也是为什么现在的定位必须是"辅助"，而不是"替代"。

---

## 四、数据安全类（预判最凶一问）

### Q13. 财务文档送外部 API（DashScope/通义千问），数据安全怎么保证？

三层说清楚，一层比一层实：**第一层**，Demo 阶段为什么用公有云 API——`调研记录.md` 第 109-113 行写得直接：自部署 VLM 推理需要 GPU 服务器（当时没有），Demo 阶段调用量小（评审跑十几张图）API 成本几乎为零，直接调 API 能省下决赛升级两周多时间里最宝贵的开发时间，这是权衡时间成本的工程选择，不是"没想过安全"。**第二层**，代码结构已经为切换做好了准备——所有出网的 VLM 调用全部收在 `agent.py::call_vlm(messages)` 一个函数里（第 42-52 行），`_agent_loop`/`direct_review`/`review()` 都只通过这一个函数发起网络请求，换供应商/换成内网地址只需要改这一个函数和 `config.py` 里的 `VLM_MODEL`/`VLM_BASE_URL` 两个常量，不需要碰 Agent Loop、Prompt、UI 的任何一行代码。**第三层**，生产路径不是纸上谈兵——服务器到位后的第一步（brief 附录服务器轨清单第 2 条）就是"验证 DashScope 内网可达"（`scripts/probe_fc.py` 跑一遍），内网自部署开源 Qwen-VL 替换 `call_vlm` 背后的实现即可，`.env` 里的 `VLM_BASE_URL` 指向内网地址就是切换的全部改动。补一句自证：我们自己的评测集因为含真实业务单据，`eval-images/README.md` 已经写了脱敏要求清单（户名/账号/卡号/身份证号/手机号/地址/公章公司全名）并且 `.gitignore` 已屏蔽图片文件不进公开仓库（`eval-images/**/*.jpg` 等规则），这是我们自己已经在按这个数据安全标准做事，不只是写在 PPT 上的口号。

---

## 附录：本文档的证据颗粒度说明

- 文件:行号 引用均在撰写本文档当次会话中用 `Read` 工具直接核对，如后续代码有变动可能漂移，遇到评委追问"给我看看"时以函数名/类名定位为准，行号仅作为当前版本的导航提示。
- TruFor 的 F1/AUC、DOCFORGE-BENCH 的校准发现，均为第三方论文/我们调研阶段整理的公开信息（`调研记录.md`），不是本项目自测数字，回答中已明确标注来源类别，避免混淆成"我们的评测结果"。
- 0.945→0.177 的缩放实验、check.jpg 的"纸张噪点误报"发现等，均为项目真实测试记录（前者见坑 #2、后者见 `docs/dev-log.md` Task 7），不是为本文档新造的示例。
