# 内容扩展研究记录（2026-09-21）

以下页面在本轮实际查阅。参考的是公开分类、表示方式和数据使用边界；未下载、复制或翻译其样本句、视频、模型权重、问卷条目。生产目录中的中文句、行为区别、修仙规则、修正系数、VAD 数值由项目原创编写。它们是小说创作的工程先验，不是心理测量结果，也不能从一个动作确诊真实人的内心状态。

| 参考项目 / 原始来源 | 采用的方法或视角 | 未采用 / 许可处理 |
|---|---|---|
| [GoEmotions](https://github.com/google-research/google-research/blob/master/goemotions/README.md) | 用细粒度情绪区分困惑、认可、愉悦等认知和关系过程 | 不导入 Reddit 文本；原有 taxonomy 的构建限制仍保持 |
| [OpenFace Action Units](https://github.com/TadasBaltrusaitis/OpenFace/wiki/Action-Units) | 区分面部部位、动作出现、强度与时间轨迹 | 不复制 FACS 手册、不打包模型，不宣称微表情唯一对应某种情绪 |
| [NTU RGB+D](https://github.com/shahroudy/NTURGB-D) | 参考全身、手部、日常操作、人际互动的覆盖分区 | 不搬运视频/骨架数据；道具操作以已知事实和手部约束重新原创 |
| [IPIP](https://www.ipip.ori.org/) 与 [多维量表目录](https://www.ipip.ori.org/newMultipleconstructs.htm) | 人格由多个连续维度组成，交互产生表现倾向 | 项目规则不是问卷，也不进行人格诊断；没有复制量表题项 |
| [EmoBank](https://github.com/JULIELab/EmoBank) | 离散标签与连续 VAD 分别表示；叙述者/读者视角不能混同 | 不导入 CC-BY-SA 语料；本轮数值不是 EmoBank 测量值 |
| [EmpatheticDialogues](https://github.com/facebookresearch/EmpatheticDialogues) | 情绪需要具体经历和对话背景，而非只有一个形容词 | 不复制对话；现有来源的 blocked/pending 状态不改 |

扩展目标以用户确认的十项为准。语义类别不同于词面不同：左右手镜像、强弱倍率、同义句、情绪标签替换都不能单独算新动作。微表情目录统计的是可用于叙事的短时动作轨迹，不是“100 种经过实验确证的微表情”。

所有 facts 都表示作者明确给出的当前事实，并且在规划时检查；例如已有泪水、指定物体在手中、对方刚刚停顿、内部视角许可。数据只表示一段局部表现，不执行物品数据库、医疗模型或完整战斗模拟。
