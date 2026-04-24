# Lantern

> 把任意 Markdown 文件变成可翻页的终端幻灯片。

```bash
slide deck.md
```

命令名取自最早的幻灯投影设备 *magic lantern*（19 世纪）。

---

## 环境要求

- **Python ≥ 3.10**
- **iTerm2（强烈推荐，用于图片）**
  图片渲染走 iTerm2 的 inline-image 协议（OSC 1337），像素保真。其他终端（Terminal.app / Ghostty / Alacritty / kitty 等）会自动回退到 Unicode 半块字符（`▀`）+ 24-bit 真彩色 —— **能看见内容但明显是色块拼出来的**，不是真正的图片。

  **如果 slide 里有图，用 iTerm2 打开。** 其他功能（文字、表格、代码、主题、键盘导航）在所有 truecolor 终端都正常。

- 依赖：`rich ≥ 13.7`、`pillow ≥ 10.0`、`typer ≥ 0.12`（`pip install` 时自动装）

---

## 安装

```bash
git clone <repo> lantern
cd lantern
pip install -e .        # 或 uv pip install -e .
```

安装后全局可用 `slide` 命令（装在你 shell 的 PATH 里）。

---

## 使用

```bash
slide deck.md           # 打开指定文件
slide                   # 无参数 → 提示拖入文件
slide --pick            # 打开 fuzzy 文件选择器
slide -t dark           # 切换到暗色主题（默认 light）
```

无参启动时，把 Finder 里的 markdown 文件**拖拽**到终端窗口即可（支持 `file://` URI、带空格路径的反斜杠转义 / 引号包裹）。空回车则回退到 fuzzy picker。

### 快捷键

| 键 | 动作 |
|---|---|
| `→` `Space` `Enter` `l` `n` | 下一页 |
| `←` `Backspace` `h` `p` | 上一页 |
| `↓` `j` `PgDn` | 长 slide 内向下翻页；已到底则下一张 |
| `↑` `k` `PgUp` | 长 slide 内向上翻页；已到顶则上一张 |
| `g` `Home` | 首页（目录） |
| `G` `End` | 末页 |
| `c` | 跳回目录 |
| `<N>` `Enter` | 跳到第 N 张 |
| `o` | 打开另一个文件 |
| `r` | 重新加载当前文件（边写边看） |
| `t` | 切换主题（light / dark / mono 循环） |
| `?` | 帮助浮层 |
| `q` `Ctrl-C` | 退出 |

---

## 分页规则

Lantern 根据标题层级自动拆分 slide：

1. 文件里有 `#` → 每个 `#` 都是一张 slide，嵌套的 `##` 作为可滚动子标题
2. 没有 `#` 但有 `##` → 每个 `##` 作为一张 slide
3. 都没有 → 整个文件是一张 slide

第一个 `#`（或 `##`）slide 自动作为**标题页**居中显示；Lantern 还会在位置 0 自动插入一张**目录页**（两级树状结构，可用 `↑↓` + Enter 跳转）。

---

## 主题

默认是 **light**（温暖米白 + 深暖紫灰 + 柔青）。放映中按 `t` 循环。

| 主题 | 配色 | 场合 |
|---|---|---|
| `light` | 暖米白底、深紫灰字、柔青+玫瑰点缀 | 日常 / 投影 |
| `dark` | 柔和深灰底（非纯黑）、柔白字、蓝紫点缀 | 夜间 / 暗环境 |
| `mono` | 无色，尊重终端默认 | SSH / tmux / 低色终端 |

所有主题都避免了 rich 默认会在 inline code 上用的反色块，改成柔和色片。表格列宽不够时**自动换行**（而不是 `…` 截断）。引用块的 `▌` 左栏和正文用分离的颜色。

---

## 配置

环境变量：

| 变量 | 默认 | 作用 |
|---|---|---|
| `LANTERN_IMG_MODE` | 自动检测 | 强制图片后端：`iterm2` 或 `ascii` |
| `LANTERN_CACHE_DIR` | `~/.cache/lantern/images` | 远程图片下载缓存目录 |

---

## 支持的 Markdown 语法

- 标题 `#` ~ `######`（`#` 和 `##` 参与分页）
- 段落、**粗体**、*斜体*、~~删除线~~、`inline code`
- 列表（有序/无序/嵌套）
- 代码块（Pygments 高亮，主题跟着 `code_theme` 走）
- 表格（宽字符友好，自动折行）
- 引用块
- 链接 `[text](url)`
- 图片 `![alt](path_or_url)`：本地路径或 http(s) URL（首次下载后缓存）

---

## 示例

```bash
slide examples/demo.md
```

`examples/demo.md` 覆盖了所有渲染路径，可直接看效果。

---

## License

MIT
