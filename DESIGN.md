# TPPT — Terminal PPT 设计文档

> 在终端里把 Markdown 以幻灯片形式优雅地放映出来。

---

## 🎯 目标

- 输入：一个 Markdown 文件
- 输出：在终端里"像 PPT 一样"逐页放映
- 必须好看：排版、颜色、居中、分页指示，该有的都要有
- 支持图片（iTerm2 / Kitty 原生，其它终端 ASCII 降级）
- 不传文件时弹出**内置文件选择器**，方向键/模糊搜索挑 `.md` 文件

---

## 🧠 核心设计决策

### 1. 分页逻辑（Slide Splitting）

**规则：**
1. 先扫描全文，统计 H1（`#`）的数量
2. 若 H1 ≥ 1 → 以 H1 作为切页符
3. 若 H1 == 0 → 降级为 H2（`##`）作为切页符
4. 若两者都没有 → 整个文档当作一页

**实现：** 用行级扫描器（不用 AST），因为代码块里的 `#` 不是标题。需要跟踪是否在 fenced code block（` ``` ` / `~~~`）内。

⚠️ **常见误解**：直接 `text.split("\n# ")` 会把代码块里 `# comment` 也当标题切掉。

### 2. 渲染引擎（Rendering）

**选型：Python + [rich](https://github.com/Textualize/rich)**

| 选项 | 优点 | 缺点 | 选用 |
|---|---|---|---|
| `rich` (Python) | Markdown/语法高亮/Box/Layout 开箱即用 | Python 启动稍慢 | ✅ |
| `glow` (Go CLI) | 已有成熟方案 | 不能定制分页和交互 | ❌ |
| `ink` (Node) | 组件化好 | 图片生态弱 | ❌ |
| `ratatui` (Rust) | 快 | Markdown 需要自己写 | ❌ |

**理由（pragmatic choice）**：`rich.markdown.Markdown` 已经把标题/列表/代码块/引用/表格全部处理好，我们只要切页 + 装饰边框 + 图片即可。

### 3. 图片渲染（Images）

终端图片是最麻烦的一块。按优先级降级：

| 终端 | 协议 | 分辨率 | 处理 |
|---|---|---|---|
| iTerm2 | Inline Images Protocol (base64 + ESC) | 原图 | 最优路径 |
| Kitty / Ghostty / WezTerm | Kitty Graphics Protocol | 原图 | 次优路径 |
| 支持 Sixel 的终端 (mlterm, foot, xterm `-ti vt340`) | Sixel | 原图 | 可选 |
| 其它（Terminal.app、Alacritty 等） | 半字符块 + 24bit color 映射 | 像素化 | **兜底** |

**检测方式：**
- `TERM_PROGRAM=iTerm.app` → iTerm2
- `TERM=xterm-kitty` 或 `KITTY_WINDOW_ID` → Kitty
- 环境变量 `TPPT_IMG_MODE` 可强制覆盖
- 都识别不了 → ASCII 半块降级

**依赖：** `Pillow`（读图 + 缩放），`imgcat`/自实现 escape sequence。

### 4. 交互与快捷键

**放映态（Slide Mode）：**

| 按键 | 行为 |
|---|---|
| `→` / `Space` / `Enter` / `l` / `j` | 下一页 |
| `←` / `Backspace` / `h` / `k` | 上一页 |
| `Home` / `g` | 第一页 |
| `End` / `G` | 最后一页 |
| 数字 + `Enter` | 跳到第 N 页 |
| `r` | 重载当前文件（开发时有用） |
| `o` | 打开文件选择器（切换文件） |
| `t` | 切换主题（dark/light/mono） |
| `?` | 显示快捷键 |
| `q` / `Esc` / `Ctrl-C` | 退出 |

**文件选择器（File Picker）：**
- 启动时没给参数 → 自动进入
- 或在放映态按 `o` 进入
- 模糊搜索当前目录下所有 `.md` / `.markdown`（递归，跳过 `node_modules`/`.git` 等）
- `↑` `↓` 移动，`/` 搜索，`Enter` 确认，`Esc` 返回

### 5. 视觉设计（Aesthetics）

**每页的布局：**

```
╭──────────────────────────────────────────────────────── TPPT ─╮
│                                                                │
│                                                                │
│                 # 一级标题（大号，居中，粗体）                 │
│                                                                │
│                                                                │
│       正文内容：列表、段落、代码块、图片...（左右留白）        │
│                                                                │
│                                                                │
╰── slides.md ─────────────────────────── 3 / 12 ── ▓▓▓░░░░ ───╯
```

**细节：**
- 外框圆角 `rounded`
- 页脚：文件名 · 当前页/总页 · 进度条
- 标题用主题强调色（cyan/magenta 渐变或纯色）
- 代码块保留 `rich` 默认的 monokai 高亮
- 每页自动**垂直居中**（如果内容短于终端高度）
- 宽度自适应终端，但正文最大 100 列（防止超宽屏拉伸难读）

**主题：**
- `dark`（默认）：深色背景，cyan 标题，white 正文
- `light`：浅色背景，magenta 标题，black 正文
- `mono`：纯文本，无颜色（便于截屏/打印）

### 6. 演讲者模式（Stretch Goal，先不做）

- 左半屏：当前页
- 右半屏：下一页预览 + HTML 注释（`<!-- speaker: ... -->`）当作演讲者备注
- 这一期**不做**，留 TODO

---

## 🏗️ 架构

```
tppt/
├── pyproject.toml           # 依赖：rich, pillow, typer
├── README.md
├── tppt/
│   ├── __init__.py
│   ├── __main__.py          # python -m tppt 入口
│   ├── cli.py               # CLI 参数解析（typer）
│   ├── parser.py            # Markdown → slides（切页逻辑）
│   ├── renderer.py          # 单页渲染（rich + 居中 + 边框）
│   ├── images.py            # 图片协议检测 + 输出
│   ├── picker.py            # 文件选择器（rich.prompt 或 自实现）
│   ├── presenter.py         # 主循环 + 键盘事件
│   ├── themes.py            # 主题配色
│   └── keys.py              # 原始模式键盘读取（termios/tty）
└── examples/
    └── demo.md              # 示范文件（带图片、代码、列表）
```

**模块边界：**

- `parser` 纯函数：`str → list[Slide]`，无副作用
- `renderer` 纯渲染：`Slide + Theme + (w,h) → Renderable`
- `presenter` 拥有主循环，调用 `renderer` + `keys` + `images`
- `images` 封装了所有终端方言

---

## 🛠️ 依赖

```toml
[project]
dependencies = [
    "rich>=13.7",
    "pillow>=10.0",
    "typer>=0.12",
]
```

**不引入** `textual`——过重，我们只要一个全屏循环 + 键盘，`rich.live.Live` + `termios` 足够了。

---

## 📋 开发阶段

### Phase 1 — MVP（最小可用）
- [x] 写设计文档
- [ ] `parser.py`：切页（H1 / H2 降级 / 代码块保护）
- [ ] `renderer.py`：单页渲染 + 圆角边框 + 页脚
- [ ] `presenter.py`：主循环 + 左右方向键翻页
- [ ] `cli.py`：`tppt path/to/file.md`

**验收：** 能放映一个纯文本 Markdown（无图片）。

### Phase 2 — 图片支持
- [ ] `images.py`：iTerm2 协议
- [ ] `images.py`：Kitty 协议
- [ ] `images.py`：半字符块降级（24bit color）
- [ ] `renderer.py`：识别 `![alt](path)` 并调用 images

**验收：** iTerm2 下能显示图片，Terminal.app 下自动降级。

### Phase 3 — 文件选择器
- [ ] `picker.py`：列出当前目录 `.md`，上下键选择
- [ ] 无参数启动时自动弹出
- [ ] 放映态 `o` 键打开

**验收：** 无参数跑 `tppt`，能挑一个文件开始放映。

### Phase 4 — 好看打磨
- [ ] 主题切换
- [ ] 页码/进度条/跳页
- [ ] 重载 `r` 键
- [ ] 帮助弹层 `?`
- [ ] `demo.md` 示范文件

---

## 🚧 已知坑 / Trade-offs

1. **Python 启动时间**（~150ms）——*pragmatic choice*，换来开发速度和 rich 的渲染质量
2. **Windows 终端**——`termios` 不可用；这一期**只支持 macOS / Linux**，Windows 留 TODO
3. **图片在非 iTerm2/Kitty 会很丑**——这是物理限制，ASCII 降级尽力而为
4. **Markdown 表格**在窄终端会很难看——依赖 `rich` 的自动换行
5. **H1/H2 降级的副作用**：文档结构不规范时可能切出空页，要过滤掉

---

## 🔭 未来（不在本期）

- 演讲者备注模式（双栏）
- 导出为 GIF / 录屏
- 远程放映（SSH + tmux 共享会话）
- Mermaid 图渲染（需要调用外部工具转 PNG）
- 动画切换效果（淡入/左右滑）
