# Character Performance Pack V2：公开来源与许可审计

> 审计日期：2026-09-21  
> 范围：Phase 0（Source Research & License Audit）  
> 说明：本文是工程风险控制记录，不构成法律意见。许可判断以本文链接的官方项目页、官方仓库、原始论文和数据使用协议为准；正式发布前仍应由项目负责人复核所下载版本附带的许可证文件。

## 1. 结论先行

Character Performance Pack 不应把所有“公开可下载”的材料视为“可并入产品”。公开访问、科研使用、允许修改、允许再分发和允许商业使用是五件不同的事。

建议采用四级准入：

| 分类 | 工程含义 |
|---|---|
| **可导入** | 可将明确许可的结构化数据或代码导入受控构建流程；仍须满足署名、同许可、NOTICE 等条件，并固定来源版本。 |
| **仅派生元数据** | 不复制原始文本、图像、视频、音频；只保存自行归纳的标签映射、统计关系、schema 映射或不具表达性的事实，并保留来源。若许可对衍生物也有限制，仍不得绕过该限制。 |
| **仅概念参考** | 只借鉴论文公开的方法、术语和系统分层，独立实现；不导入数据、不复制手册图表/示例/长段文字。 |
| **待确认** | 官方许可缺失、相互冲突、需签署协议，或商业/再分发边界不清。未经书面确认不得进入发布包。 |

### 汇总矩阵

| 来源 | 推荐状态 | 可用于本项目的安全范围 | 主要阻断点 |
|---|---|---|---|
| GoEmotions | **仅派生元数据** | 27+neutral 标签关系、统计启发、ontology 映射 | 仓库根目录 Apache-2.0 与 Reddit 原始评论权利不是同一层；数据目录无独立、清晰的数据许可声明 |
| EmoBank | **可导入（隔离 BY-SA）** | VAD 标注、reader/writer perspective、评测切分 | CC BY-SA 4.0；再分发适配材料需署名和同许可；原始语料来自多个上游来源 |
| FACS | **仅概念参考** | AU 思想、面部动作与情绪解耦、编码层设计 | 官方手册/训练材料为付费、个人许可材料，不是开放数据集 |
| SAMM | **待确认** | 论文中公开的字段设计；获批后仅在隔离研究环境使用 | 仅非商业研究、签协议、禁止再分发/修改，且公开协议含删除期限与严格 IP 条款 |
| CASME II | **待确认** | onset/apex/offset、AU/情绪标注 schema 的概念参考 | 需申请并签许可；官方公开页未给出可概括为开源许可的商业/再分发授权 |
| SMIC | **待确认** | 三类情绪和多相机设置的概念参考 | 需联系作者并签协议；无可核验的开放商业/再分发许可 |
| CPED | **仅派生元数据** | 13 情绪、Big Five、19 dialogue acts、scene 等字段映射 | 仓库 Apache-2.0，但语料源自 40 部电视剧；代码许可不能自动清除第三方影视内容权利 |
| EmpatheticDialogues | **待确认** | 32 情绪场景 taxonomy；非商业研究可按原始许可使用 | 原始仓库为 CC BY-NC 4.0，ParlAI 副本却声明 CC BY 4.0，存在版本/授权冲突 |
| DailyDialog | **仅概念参考** | emotion / dialogue act / topic 三层 schema | 官方分发被 ParlAI 明示为“free for use in research”；商业、修改与再分发未获明确授权 |
| PersonaChat | **可导入** | persona facts、角色条件化对话结构 | ParlAI 任务级许可为 CC BY 4.0；必须署名并固定任务版本，不能误用 ParlAI 根 MIT 作为数据许可 |
| LIGHT | **待确认** | world state → persona → action/dialogue 的建模思路 | 官方项目页提供下载方式但未给数据级许可证；ParlAI 根 MIT 仅能可靠覆盖代码，不能推定覆盖数据 |
| BML / SAIBA | **仅概念参考** | Planner/Realizer 分层、同步点、组合、ground state、feedback | BML 1.0 规范可读但未发现明确复用许可证；规范文本与独立实现需要分开处理 |

## 2. 逐项审计

### 2.1 GoEmotions

**建议用途**

- 细粒度情绪标签种子与层级设计参考。
- 多标签共现、情绪相关性和 neutral 处理的算法验证。
- 不直接复制评论文本时，可用于构造 `source_concept -> canonical_emotion` 映射。

**获取方式**

- [Google Research 官方目录](https://github.com/google-research/google-research/tree/master/goemotions)
- [ACL 原始论文](https://aclanthology.org/2020.acl-main.372/)
- 官方目录 README 给出 Google Cloud Storage 的原始 CSV 与 train/dev/test 下载地址。

**许可与限制**

- `google-research` 仓库根许可证为 [Apache License 2.0](https://github.com/google-research/google-research/blob/master/LICENSE)，可明确用于仓库代码和被该许可证覆盖的作品。
- GoEmotions 数据目录 README 没有单独写明“Reddit 评论文本本身均按 Apache-2.0 授权”。数据包含 Reddit 评论、作者名、subreddit 和时间戳等字段；仓库许可不应被自动解释为 Google 能替所有评论作者授予完整版权。
- 论文与模型卡还指出代表性偏差、潜在冒犯内容和 Reddit 用户群偏差。

**推荐分类：仅派生元数据。** 默认只导入标签表、标签 ID、统计关系和项目自行生成的 ontology 映射；不把 Reddit 评论正文、用户名或原始行记录随产品分发。若未来需要训练或分发原始数据衍生模型，应另做 Reddit 数据条款与隐私评估。

### 2.2 EmoBank

**建议用途**

- Valence–Arousal–Dominance 连续空间的标定与测试。
- 区分 writer perspective 与 reader perspective。
- 校准离散 emotion label 到 VAD 分布，而不是把一个标签绑定到固定坐标。

**获取方式**

- [JULIE Lab 官方 GitHub 仓库](https://github.com/JULIELab/EmoBank)
- [EACL 2017 原始论文](https://aclanthology.org/E17-2092/)

**许可与限制**

- 官方 README 明示 **CC BY-SA 4.0**，见 [许可证正文](https://creativecommons.org/licenses/by-sa/4.0/legalcode)。允许分享与改编，包括商业使用，但必须署名；分享适配材料时须采用兼容的 ShareAlike 许可。
- README 明示原始文本来自 MASC、SemEval 2007 Task 14，pilot 还含 Stanford Sentiment Treebank。CC 许可只覆盖许可方有权许可的权利；因此必须保留上游归属信息并检查具体子集。
- ShareAlike 对整个 Performance Pack 的传播范围可能产生架构争议，不宜把 EmoBank 原句混入核心 ontology 文件。

**推荐分类：可导入（隔离 BY-SA）。** 将 EmoBank adapter、原始数据缓存和生成的逐句适配结果放入独立、可替换的 `sources/emobank/` 边界并随附 CC BY-SA 4.0、署名和修改说明。主 ontology 优先只保存独立生成的参数/规则，并让发布流程单独判断其是否构成适配材料。

### 2.3 FACS（Facial Action Coding System）

**建议用途**

- 以 Action Unit 描述可观察的面部动作，而非把表情永久绑定到情绪。
- 设计 `facial_action -> semantic_facial_state -> narrative_hint` 的三层 adapter。
- 支持 AU 强度、左右侧、共现、onset/apex/offset 与可见度。

**获取方式**

- [Paul Ekman Group 官方 FACS 说明与 FAQ](https://www.paulekman.com/faq/)
- [官方 FACS 产品页](https://www.paulekman.com/facial-action-coding-system/)

**许可与限制**

- 官方说明把 FACS 定义为基于解剖、由 Action Units 组成的面部动作编码系统。
- 官方手册是付费下载；官方条款/FAQ说明训练工具为个人许可使用，照片与出版还可能需要单独许可。
- “AU 作为科学概念”和“官方手册中的文字、照片、图表、训练视频与测试材料”必须区分。不得把购买的手册内容、示例图片或测试题复制到仓库。

**推荐分类：仅概念参考。** 独立编写最小 AU 兼容层，引用论文/系统名称；不要宣称实现了官方认证版 FACS，也不要复制官方表格、图像和长描述。

### 2.4 SAMM

**建议用途**

- 微表情时序字段：onset、apex、offset、duration。
- AU、objective class、可见度、头部运动/眨眼区分的 schema 参考。
- 用于隔离的科研 benchmark，不作为产品运行时素材库。

**获取方式**

- [SAMM 官方 Release Agreement V2](https://megc2025.github.io/files/SAMM_ReleaseAgreementV2.pdf)
- [官方申请入口（MEGC）](https://megc2026.github.io/challenge.html)
- [原始论文 DOI](https://doi.org/10.1109/TAFFC.2016.2573832)

**许可与限制**

- 协议限定为非商业的微动作及相关研究；其他用途须向 Manchester Metropolitan University 书面申请并逐案审批。
- 未经书面批准，不得在任何形式下再分发、发表、复制或传播；不得修改或商业使用。
- 发表只能按协议许可的科学摘要形式进行，部分参与者图像明确禁止发表。
- 协议要求引用、提交出版物，并包含 IP 归属、终止、审计、GDPR 责任和数据销毁条款；当前公开 V2 还写有“不晚于 2026-01-30 删除原始数据”的期限。该日期已早于本审计日期，不能假定旧协议仍可用于新访问。

**推荐分类：待确认。** 在获得最新、由本项目主体签署的协议前，不下载、不缓存、不导入。即使获批，也只放入访问控制的研究环境，不进入可分发包；产品 ontology 只可依据论文公开事实独立设计。

### 2.5 CASME II

**建议用途**

- 微表情 clip 的 onset/apex/offset 与 AU 标注结构。
- 比较 `emotion label`、自我报告、诱发材料与 AU 之间的不确定关系。
- 作为研究环境中的 micro-expression benchmark。

**获取方式**

- [中国科学院心理研究所微表情实验室数据库申请页](https://melabipcas.github.io/melab/zh/databases.html)
- [CASME II 原始开放论文（PLOS ONE）](https://doi.org/10.1371/journal.pone.0086041)
- 官方申请页要求下载空白 License Agreement 并提交签署件。

**许可与限制**

- 论文是 CC BY 的开放文章，不等于人脸数据库本身也是 CC BY。
- 官方数据库页采取申请制和签署许可制；未在公开页面发现足以确认商业使用、修改和再分发均获许可的开放许可证。
- 数据含可识别人脸和实验参与者材料，除版权外还涉及隐私、人格权与伦理要求。

**推荐分类：待确认。** 未签署适用于本项目的最新版协议前，只可引用论文中的公开 schema 和统计事实；不得导入帧、clip、参与者标识或逐样本标签。

### 2.6 SMIC

**建议用途**

- 高速、普通可见光和近红外多模态采集条件的对照。
- 三类标签（positive / negative / surprise）与动作时间窗的 benchmark 参考。
- 说明微表情标签粒度受数据采集与自我报告方法影响。

**获取方式**

- [原始论文 DOI](https://doi.org/10.1109/FG.2013.6553717)
- [作者团队关于 SMIC 数据可用性的开放论文说明](https://doi.org/10.1371/journal.pone.0124674)
- 原始数据需联系 University of Oulu 研究团队并签署协议；历史官方入口为 `http://www.cse.oulu.fi/SMICDatabase`，现有可用性可能变化。

**许可与限制**

- 原始作者的公开 data availability 声明明确：其论文作者无权重新发布 SMIC，使用者需向数据持有人申请并签署 agreement。
- 未找到可核验的开放数据许可证来确认商业使用、修改或再分发权利。
- 数据包含人脸，应另行满足隐私、伦理与安全存储要求。

**推荐分类：待确认。** 仅把论文公开的实验设计和字段作为概念输入。任何原始数据或逐样本标注使用都以获批协议为前置条件。

### 2.7 CPED

**建议用途**

- 中文对话中的 emotion + sentiment + Big Five + dialogue act + scene 联合 schema。
- 提炼 speech-performance modifier，而不是复制电视剧台词。
- 用标签分布测试人格、情绪与对话行为是否被错误地做成一一映射。

**获取方式**

- [CPED 官方 GitHub 仓库](https://github.com/scutcyr/CPED)
- [官方论文](https://arxiv.org/abs/2205.14727)
- 仓库亦指向 LUGE 数据平台。

**许可与限制**

- 官方仓库带 [Apache-2.0 LICENSE](https://github.com/scutcyr/CPED/blob/main/LICENSE)，该许可允许修改、分发和商业使用，但须保留许可/NOTICE/修改声明等。
- 论文明确语料来自 **40 部中国电视剧**，并说明发布文本与音视频特征时考虑了版权声明、隐私和视频平台条款。这意味着“仓库代码/自有标注的 Apache-2.0”不应自动扩张为对第三方台词、影视画面或声音的完整再许可。
- 项目发布包若包含原始台词或可反推影视内容的特征，存在额外版权风险。

**推荐分类：仅派生元数据。** 可导入字段名、标签集合、标签映射和自行统计的非表达性关系；默认不分发台词、音频、视频或可逆特征。若要训练模型，须把训练环境与发布包分离，并单独评估数据许可和输出模型风险。

### 2.8 EmpatheticDialogues

**建议用途**

- 情绪情境、speaker/listener 角色与同理回应之间的关系。
- 32 种情绪场景 taxonomy 和“情境触发—反应策略”建模。
- 评估对话表现是否能体现理解而不是复述情绪词。

**获取方式**

- [原始 facebookresearch 仓库](https://github.com/facebookresearch/EmpatheticDialogues)
- [原始仓库许可证](https://github.com/facebookresearch/EmpatheticDialogues/blob/main/LICENSE)
- [ParlAI 任务目录](https://github.com/facebookresearch/ParlAI/tree/main/parlai/tasks/empathetic_dialogues)
- [ParlAI 任务级许可证文件](https://github.com/facebookresearch/ParlAI/blob/main/parlai/tasks/empathetic_dialogues/LICENSE_DOCUMENTATION)
- [ACL 原始论文](https://aclanthology.org/P19-1534/)

**许可与限制**

- 原始仓库根 LICENSE 是 **CC BY-NC 4.0**：允许非商业分享和改编，须署名；禁止商业使用。
- ParlAI 的任务 README 和任务级许可证却声明 **CC BY 4.0**，允许商业使用但仍须署名。
- 两个官方分发渠道对同名数据给出不一致许可。可能是后续重新授权，也可能只适用于特定副本/版本；没有书面确认时不能将较宽松许可追溯套用于从原始仓库下载的数据。

**推荐分类：待确认。** 若确需导入，必须只从 ParlAI 指定构建脚本取得明确受 CC BY 4.0 覆盖的 artifact，记录 commit、下载 URL、checksum 和任务级许可证快照；在完成这一证据链前，商业产品只使用论文公开的 taxonomy 概念，不使用对话文本。

### 2.9 DailyDialog

**建议用途**

- `topic + emotion + dialogue_act` 的多层标注设计。
- 日常对话中 speech act 与情绪标签的联合评测。
- 对 neutral 占比、标签不均衡和日常语言风格做方法参考。

**获取方式**

- [ACL 原始论文](https://aclanthology.org/I17-1099/)
- [ParlAI 任务实现](https://github.com/facebookresearch/ParlAI/tree/main/parlai/tasks/dailydialog)
- 原作者历史下载地址由论文与 ParlAI 构建脚本引用；其可用性需现场复核。

**许可与限制**

- ParlAI 的数据 teacher 源码明确写道：原始数据版权属于论文作者，**free for use in research**；这不是允许商业使用、修改与再分发的标准开源许可。
- ParlAI 仓库根 MIT 许可覆盖 ParlAI 代码，不能据此推断 DailyDialog 原始数据也是 MIT。
- 第三方镜像上出现的许可证标记不能替代原作者授权，本文不采用镜像许可作为准入依据。

**推荐分类：仅概念参考。** 在获得作者的明确书面许可前，不把原始对话或逐句标签导入可分发产品；只独立实现其公开论文中的三层 schema 思想。

### 2.10 PersonaChat

**建议用途**

- persona facts 与对话历史分离的数据结构。
- 人格条件只作为选择/措辞 modifier，而不是直接决定具体动作。
- 测试同一角色在不同 persona grounding 下的稳定性和矛盾检测。

**获取方式**

- [ParlAI 官方 PersonaChat 项目页](https://parl.ai/projects/personachat/)
- [ParlAI 任务目录](https://github.com/facebookresearch/ParlAI/tree/main/parlai/tasks/personachat)
- [PersonaChat 任务级许可证](https://github.com/facebookresearch/ParlAI/blob/main/parlai/tasks/personachat/LICENSE_DOCUMENTATION)
- [ACL 原始论文](https://aclanthology.org/P18-1205/)

**许可与限制**

- 任务级许可证是 **CC BY 4.0**，允许复制、改编和商业使用；分享时须按许可证要求署名、链接许可证并标明修改。
- ParlAI 根 MIT 是框架代码许可，不应替代 PersonaChat 的任务级 CC BY 4.0 数据许可。
- persona 与对话来自众包，仍应做个人信息、刻板印象和敏感内容过滤；许可不等于内容安全保证。

**推荐分类：可导入。** 固定 ParlAI commit、任务级许可证与数据 checksum；原始语句放在 source layer，不直接进入核心 ontology。公开发布适配数据时保留 attribution 和 modification notice。

### 2.11 LIGHT

**建议用途**

- 同一 agent 同时执行 speech、emote、physical action 的 world-grounded 结构。
- location、objects/affordances、characters、previous actions 对下一行为选择的约束。
- 关系、场景和世界状态进入 Performance Planner 的参考实现。

**获取方式**

- [ParlAI 官方 LIGHT 项目页](https://parl.ai/projects/light/)
- [ParlAI LIGHT task](https://github.com/facebookresearch/ParlAI/tree/main/parlai/tasks/light_dialog)
- [ACL 原始论文](https://aclanthology.org/D19-1062/)

**许可与限制**

- 官方项目页提供 `light_dialog` / `light_dialog_wild` 的获取方法和引用信息，但未在页面上声明明确的数据级许可证。
- LIGHT task 目录未提供类似 PersonaChat 的任务级 `LICENSE_DOCUMENTATION`。
- ParlAI 根目录的 MIT 许可可用于框架代码，但不能在缺少数据级声明时安全推定覆盖 crowdsourced locations、objects、characters 和 dialogues。
- 原始集、WILD、quests、ATOMIC-LIGHT 是不同 artifact，不应共用一个模糊的“LIGHT license”字段。

**推荐分类：待确认。** 当前只按论文借鉴 world-grounded planner 概念。若未来导入，逐 artifact 向发布者确认许可，并分别记录来源、版本、checksum 与授权文件。

### 2.12 BML / SAIBA

**建议用途**

- 采用 SAIBA 的 Intent Planner → Behavior Planner → Realizer 分层。
- 借鉴 BML 的多通道行为块、同步点、composition、feedback、failure/fallback。
- 将 ground state、临时行为与 residual/shift 行为映射到 Continuity Engine。

**获取方式**

- [BML 1.0 标准 PDF](https://repository.cs.ru.is/attachments/download/843/bml-standard-1.pdf)
- [SAIBA/BML 原始框架论文（ACM DOI）](https://doi.org/10.1145/1823746.1823763)

**许可与限制**

- BML 1.0 规范公开描述 XML 语法、语义、同步、composition 和 feedback，但在已核验的规范文本中未发现明确的文档复用许可证或开放源码授权。
- 公开标准的思想、接口原则和不受版权保护的事实，与规范文本、示例表达、schema 文件及商标/兼容性声明不是一回事。
- 在未经确认前，不复制规范中的大段文字、完整示例或官方 schema，也不宣称 “BML compliant”。

**推荐分类：仅概念参考。** 采用独立命名和独立 schema 实现相同的架构思想；如需要 BML XML 互操作或兼容性声明，再向规范维护者确认授权与合规测试要求。

## 3. 实施文档必须落地的许可控制

### 3.1 数据与代码许可证分离

每个 source 必须至少拆成：

```yaml
source_id: empathetic_dialogues_parlai
artifact_kind: dataset
distribution_channel: parlai
upstream_project: EmpatheticDialogues
source_url: https://github.com/facebookresearch/ParlAI/...
revision: <commit SHA>
checksum: <sha256>
license_id: CC-BY-4.0
license_url: https://github.com/facebookresearch/ParlAI/.../LICENSE_DOCUMENTATION
license_snapshot: sources/licenses/empathetic_dialogues-parlai-<sha>.txt
license_scope: dataset_artifact
commercial_use: allowed
redistribution: allowed_with_attribution
modification: allowed_with_attribution
personal_data: crowdsourced_dialogue
review_status: approved
reviewed_at: 2026-09-21
```

禁止只记录仓库根许可证。`repository_code_license`、`dataset_license`、`model_license`、`paper_license` 和 `upstream_content_rights` 必须是不同字段。

### 3.2 Adapter 输出分层

```text
raw/                 # 不进 Git；按协议访问
normalized-private/  # 逐样本转换；不默认发布
derived-metadata/    # 标签映射、统计、schema 对齐
ontology/            # 项目原创的规范化概念
examples/            # 只用原创或明确可发布样例
```

`derived-metadata` 不是自动免责区。若它保留可识别原文、逐样本可逆映射或受限数据的表达性选择，仍可能受原许可约束。

### 3.3 构建门禁

发布构建只允许以下组合：

1. `review_status == approved`；
2. `license_snapshot` 存在且 checksum 固定；
3. 商业构建中 `commercial_use != prohibited/unknown`；
4. `redistribution != prohibited/unknown`，或该 artifact 被明确排除；
5. 所需 attribution、NOTICE、ShareAlike 文件已生成；
6. 含人脸、声音、用户名、persona 或影视台词的数据通过隐私与第三方权利检查。

任何 `待确认` source 都必须在 CI 中默认失败，而不是仅打印 warning。

### 3.4 当前推荐的 Phase 0 决策

- **可立即进入实现**：PersonaChat 的固定 ParlAI 任务版本；EmoBank 的隔离 BY-SA adapter。
- **可进入 ontology 研究但不导入原文/媒体**：GoEmotions、CPED。
- **只做独立概念实现**：FACS、DailyDialog、BML/SAIBA。
- **必须等授权或版本证据链**：SAMM、CASME II、SMIC、EmpatheticDialogues、LIGHT。
- 所有示例、单元测试和 renderer golden cases 优先使用项目原创合成输入，避免测试夹具反向携带受限语料。

## 4. 最小归属清单

后续 `NOTICE-SOURCES.md` 至少应列出：来源名、作者/机构、论文、数据主页、所用版本、许可证、修改说明、是否包含原始数据、是否允许商业使用。对于只做概念参考的来源，也保留论文引用，但不得用“derived from dataset”描述未实际导入的数据。

## 5. 尚需书面确认的问题

1. Google 是否对 GoEmotions 的 Reddit 评论文本与全部 annotation artifact 明确授予与根仓库相同的 Apache-2.0 权利。
2. CPED 的 Apache-2.0 对电视剧台词、音频/视频特征分别覆盖到什么范围，是否允许商业再分发和模型训练。
3. EmpatheticDialogues 从原始 CC BY-NC 4.0 到 ParlAI CC BY 4.0 是否为正式重新授权；具体从哪个版本、哪个 artifact 起生效。
4. LIGHT 原始数据、WILD、quests 与 ATOMIC-LIGHT 各自的数据许可证。
5. CASME II、SMIC、SAMM 的最新版协议、当前申请入口、商业用途与衍生标注/模型发布规则；SAMM V2 的 2026-01-30 删除期限如何适用于新申请。
6. BML 1.0 规范文本、官方 schema、示例以及 “BML compliant” 标识的复用条件。

