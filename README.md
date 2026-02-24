# OpenNovel

> 多智能体 AI 网文创作与一键发布系统

OpenNovel 是一套完全基于 **Claude** 驱动的中文网络小说自动创作框架。多个专职 AI 智能体（规划、写作、编辑、审稿、记忆）通过 **LangGraph** 工作流协同工作，自动完成从选题立意到章节成稿的全流程，并可一键发布到**番茄小说**平台。

---

## 功能特性

| 功能 | 说明 |
|------|------|
| **多智能体协作** | 规划 / 写作 / 编辑 / 审稿 / 记忆管理各司其职 |
| **LangGraph 工作流** | 条件路由、错误恢复、自动重试，全程有状态管理 |
| **向量化长期记忆** | ChromaDB 存储章节摘要与角色状态，保证跨章节一致性 |
| **质量控制系统** | 多维度审稿（字数、情节、文笔、AI 痕迹检测） |
| **一键发布番茄** | 通过浏览器自动化直接上传草稿或正式发布 |
| **对话式 AI 助手** | 自然语言交互，AI 自动调用工作流执行操作 |
| **完整 CLI** | 命令行控制全部功能，支持 TUI 界面 |

---

## 效果演示

```
你> 我想写一个修仙小说，主角是废材少年逆袭，30章
AI> 好的，开始规划……

  ✓ 分析类型与读者期待
  ✓ 构建故事架构与角色体系
  ✓ 设计冲突节奏与章节大纲
  ✓ 规划完成！《破天传承》— 30章大纲已生成

你> 写前5章
AI> 开始写作……

  ✓ 第1章  废材 (2,341字)
  ✓ 第2章  机缘 (2,298字)
  ✓ 第3章  觉醒 (2,512字)
  ✓ 第4章  崛起 (2,187字)
  ✓ 第5章  锋芒 (2,334字)

你> 帮我把第1章开头改得更吸引人
AI> 好的，我来修改……
```

---

## 系统架构

```
用户输入
   │
   ▼
CLI / TUI / 对话界面
   │
   ▼
LangGraph 工作流
   │
   ├─ PlannerAgent          规划大纲、角色、冲突
   ├─ WriterAgent           创作章节初稿
   ├─ EditorAgent           润色文本、调整字数
   ├─ ReviewerAgent         多维度质量审核
   ├─ MemoryManagerAgent    管理跨章节上下文
   └─ PublisherAgent        发布到番茄小说
         │
         ├─ SQLite          小说/章节/角色持久化
         └─ ChromaDB        向量化记忆检索
```

---

## 快速开始

### 前置要求

- Python 3.10+
- [Claude Code](https://claude.ai/code) CLI（处理 Anthropic API 认证）
- 番茄小说账号（仅发布功能需要）

### 安装

```bash
git clone https://github.com/Cppys/opennovel.git
cd opennovel
pip install -r requirements.txt
playwright install chromium
```

### 配置

```bash
cp .env.example .env
# .env 中默认配置开箱即用，无需修改 API Key
# Claude 认证由 Claude Code CLI 自动处理
```

### 运行

```bash
# 进入 AI 对话模式（推荐新手）
opennovel

# 直接创建新小说大纲
opennovel new -g 玄幻 -p "少年偶得上古传承，在万族林立的世界中崛起"

# 写章节
opennovel write -n 1 -c 1-10

# 查看状态
opennovel status -n 1

# 发布到番茄小说
opennovel publish -n 1 -c all
```

---

## 详细安装

### 1. 克隆仓库

```bash
git clone https://github.com/Cppys/opennovel.git
cd opennovel
```

### 2. 创建虚拟环境

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 安装 Playwright 浏览器（仅发布功能需要）

```bash
playwright install chromium
```

### 5. 配置环境变量

```bash
cp .env.example .env
```

`.env` 默认配置：

```env
# 使用的 Claude 模型（需要有效的 Claude Code 登录）
LLM_MODEL_WRITING=claude-opus-4-6
LLM_MODEL_EDITING=claude-opus-4-6
LLM_MODEL_PLANNING=claude-opus-4-6

# 章节字数范围
CHAPTER_MIN_CHARS=2050
CHAPTER_MAX_CHARS=2300

# 审稿失败时最大重写次数
MAX_REVISIONS=3
```

### 6. 安装为命令行工具（可选）

```bash
pip install -e .
# 之后可直接使用 opennovel 命令
```

---

## CLI 命令参考

### `opennovel` — 对话模式

```bash
opennovel              # 进入 AI 对话，不绑定小说
opennovel -n 1         # 绑定小说 ID=1 进入对话
```

AI 会自动理解意图并调用工作流，例如：
- "帮我写一个都市小说" → 自动规划大纲
- "继续写第6章" → 自动执行写作工作流
- "把第3章改得更有张力" → 直接修改数据库

### `opennovel new` — 创建新小说

```bash
opennovel new \
  -g "玄幻" \
  -p "废材少年获得上古神魔传承，踏上逆天之路" \
  -c 30 \
  --ideas "主角性格腹黑，有系统，女主是宗门大师姐"
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `-g` / `--genre` | 小说类型 | 必填 |
| `-p` / `--premise` | 核心设定 | 必填 |
| `-c` / `--chapters` | 目标章节数 | 30 |
| `--ideas` | 补充想法 | — |

### `opennovel write` — 写章节

```bash
opennovel write -n 1 -c 1-10    # 写第 1-10 章
opennovel write -n 1 -c 1,3,5   # 写指定章节
opennovel write -n 1 -c next    # 写下一章
opennovel write -n 1 -c all     # 写全部未完成章节
```

### `opennovel publish` — 发布到番茄小说

```bash
opennovel publish -n 1 -c all           # 发布全部已审稿章节
opennovel publish -n 1 -c 1-5 -m draft  # 保存为草稿
```

首次使用需先登录：

```bash
opennovel setup-browser   # 打开浏览器，扫码登录番茄小说
```

### 其他命令

```bash
opennovel status          # 列出所有小说
opennovel status -n 1     # 查看小说详情（章节、角色、进度）
opennovel list-chapters -n 1    # 列出所有章节
opennovel list-characters -n 1  # 列出所有角色
```

---

## 工作流详解

### 创作流程（每章）

```
加载上下文（向量检索前文摘要）
      ↓
WriterAgent 生成初稿
      ↓
EditorAgent 润色 + 调整字数
      ↓
ReviewerAgent 多维度审核
   ├─ 通过（评分 ≥ 7）→ 存入数据库
   └─ 未通过 → 重新编辑（最多 MAX_REVISIONS 次）
      ↓
MemoryManagerAgent 更新记忆摘要
      ↓
每 N 章触发全局一致性审查
```

### 审稿维度

ReviewerAgent 从以下维度评分（满分 10 分，≥7 视为通过）：

- **字数达标**：是否在 2050–2300 字范围内
- **情节完整性**：是否紧扣章节大纲
- **文笔质量**：句式变化、对话自然度
- **AI 痕迹检测**：是否存在"突然"过多、程式化开头等问题
- **标点规范**：中文全角标点、对话引号、省略号用法
- **上下文连贯**：与前章剧情是否衔接

### 记忆系统

ChromaDB 维护三个向量集合：

| 集合 | 内容 | 用途 |
|------|------|------|
| `chapter_summaries` | 每章摘要 | 写新章时检索前文 |
| `character_states` | 角色在各章的状态 | 保持角色行为一致 |
| `world_events` | 重要剧情事件 | 伏笔与呼应 |

---

## 项目结构

```
opennovel/
├── agents/                 # AI 智能体
│   ├── base_agent.py       # 基础类（提示词加载、LLM 调用）
│   ├── planner_agent.py    # 规划（大纲、角色、冲突设计）
│   ├── writer_agent.py     # 写作
│   ├── editor_agent.py     # 编辑润色
│   ├── reviewer_agent.py   # 质量审核
│   ├── memory_manager_agent.py
│   └── publisher_agent.py  # 番茄小说发布
│
├── workflow/               # LangGraph 工作流
│   ├── graph.py            # 主工作流图（节点 + 路由）
│   ├── state.py            # 全局状态定义（TypedDict）
│   ├── conditions.py       # 路由条件函数
│   └── callbacks.py        # 进度回调
│
├── models/                 # 数据模型
│   ├── database.py         # SQLite CRUD
│   ├── novel.py            # Novel / Volume
│   ├── chapter.py          # Chapter / Outline
│   └── character.py        # Character / WorldSetting / PlotEvent
│
├── memory/                 # 向量记忆系统
│   ├── chroma_store.py     # ChromaDB 操作
│   └── memory_retriever.py # 语义检索
│
├── publisher/              # 番茄小说集成
│   ├── fanqie_client.py    # HTTP API 客户端（通过浏览器 fetch）
│   ├── auth.py             # 登录认证
│   └── browser.py          # Playwright 浏览器管理
│
├── cli/                    # 命令行界面
│   ├── main.py             # Click CLI 入口
│   ├── chat.py             # 对话会话（AI 动作系统）
│   └── tui.py              # Textual TUI 界面
│
├── config/
│   ├── settings.py         # Pydantic 配置
│   ├── prompts/            # AI 提示词模板（Markdown）
│   └── exceptions.py       # 异常体系
│
├── tools/
│   ├── agent_sdk_client.py # Claude Agent SDK 封装
│   ├── text_utils.py       # 中文文本处理工具
│   └── style_analyzer.py   # 写作风格分析
│
├── tests/                  # 测试套件
├── .env.example
├── requirements.txt
└── pyproject.toml
```

---

## 技术栈

| 组件 | 技术 |
|------|------|
| AI 模型 | Claude（claude-opus-4-6 / sonnet-4-6） |
| 智能体 SDK | [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) |
| 工作流编排 | [LangGraph](https://github.com/langchain-ai/langgraph) |
| 向量数据库 | [ChromaDB](https://www.trychroma.com/) |
| 关系数据库 | SQLite |
| 浏览器自动化 | [Playwright](https://playwright.dev/) |
| CLI 框架 | [Click](https://click.palletsprojects.com/) + [Rich](https://github.com/Textualize/rich) |
| TUI 框架 | [Textual](https://github.com/Textualize/textual) |
| 中文分词 | [jieba](https://github.com/fxsjy/jieba) |
| 嵌入模型 | [sentence-transformers](https://www.sbert.net/) |

---

## 番茄小说发布

### 初次配置

1. 运行 `opennovel setup-browser`，浏览器窗口打开
2. 在番茄小说手动扫码或输入账号密码登录
3. 登录成功后关闭窗口，凭据已自动保存

### 发布流程

1. 在 [fanqienovel.com](https://fanqienovel.com) 作家后台**手动创建**书籍
2. 运行 `opennovel publish -n 1 -c all`
3. 程序自动拉取你的书单，用方向键选择要绑定的书
4. 确认后自动上传所有已审稿章节

> **注意**：番茄平台对 AI 生成内容有相关规定，发布前请了解平台政策。

---

## 开发指南

### 运行测试

```bash
pytest tests/                        # 全部测试
pytest tests/ -m "not integration"  # 跳过需要真实 API 的测试
pytest tests/ -v -k "test_writer"   # 运行指定测试
```

### 自定义提示词

所有提示词在 `config/prompts/*.md`，直接编辑即可。使用 `## 节点名称` 分割不同节点的提示词。

### 添加新智能体

```python
# agents/my_agent.py
from agents.base_agent import BaseAgent

class MyAgent(BaseAgent):
    async def run(self, state):
        prompt = self._load_prompt("my_agent")
        result = await self.llm.chat(prompt)
        return result
```

### 环境变量说明

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_MODEL_WRITING` | 写作使用的模型 | `claude-opus-4-6` |
| `LLM_MODEL_EDITING` | 编辑使用的模型 | `claude-opus-4-6` |
| `LLM_MODEL_PLANNING` | 规划使用的模型 | `claude-opus-4-6` |
| `CHAPTER_MIN_CHARS` | 章节最小字数 | `2050` |
| `CHAPTER_MAX_CHARS` | 章节最大字数 | `2300` |
| `MAX_REVISIONS` | 审稿失败最大重写次数 | `3` |
| `GLOBAL_REVIEW_INTERVAL` | 每 N 章触发全局一致性检查 | `5` |

---

## 常见问题

**Q: 需要 Anthropic API Key 吗？**
A: 通过 Claude Code CLI 使用时无需手动配置 API Key，CLI 自动处理认证。

**Q: 番茄小说发布失败怎么办？**
A: 先运行 `opennovel setup-browser` 重新登录。如果书籍未创建，需先在番茄作家后台手动建书。

**Q: 生成的章节质量不满意？**
A: 可以在 `config/prompts/writer.md` 中调整写作提示词，或通过对话直接让 AI 修改特定章节。

**Q: 支持其他发布平台吗？**
A: 目前仅支持番茄小说。欢迎 PR 添加其他平台（晋江、起点等）。

---

## 贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/your-feature`
3. 提交更改：`git commit -m "Add your feature"`
4. 推送分支：`git push origin feature/your-feature`
5. 创建 Pull Request

---

## License

[MIT License](LICENSE)

---

## 致谢

- [Anthropic](https://anthropic.com) — Claude 模型与 Agent SDK
- [LangChain](https://langchain.com) — LangGraph 工作流框架
- [Playwright](https://playwright.dev) — 浏览器自动化
