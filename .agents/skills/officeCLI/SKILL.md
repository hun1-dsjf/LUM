---
version: "1.0.0"
name: officeCLI
description: 操作 Office 文档（Word/Excel/PPT）的命令行技能
---

# officeCLI 技能

## 触发条件
当用户需要**读取、创建、修改 Word / Excel / PPT / PPTX** 文档时，必须调用本技能。

## 工具路径
可执行文件 officecli-win-x64.exe 与本 SKILL.md 位于同一目录。
调用 runCli 时，请先定位 officecli-win-x64.exe 的绝对路径，再执行。

## 使用规则

### 第一步：检查命令格式
**不要猜命令！** 如果不清楚 officecli 的子命令、属性名、参数格式，
**先调用 loadSkill 读取同目录下的 `office_cli_manual.md`**，或执行：

```bash
officecli help                          # 查看所有命令和全局选项
officecli help docx                     # 查看 Word 元素列表
officecli help docx paragraph           # 查看某个元素的完整 schema
officecli help xlsx cell                # 查看 Excel 单元格属性
officecli help pptx slide               # 查看 PPT slide 属性
```

### 第二步：基本命令模式

| 动词 | 用途 | 示例 |
|------|------|------|
| `create` | 创建空文档（类型由扩展名决定） | `officecli create report.docx` |
| `view` | 查看文档结构/统计/文本 | `officecli view data.xlsx outline` |
| `get` | 获取节点及子元素 | `officecli get data.xlsx /Sheet1/A1 --json` |
| `query` | CSS 风格选择器查询 | `officecli query report.docx 'paragraph[style=Heading1]'` |
| `set` | 修改元素属性 | `officecli set data.xlsx /Sheet1/A1 --prop value="姓名"` |
| `add` | 添加元素 | `officecli add report.docx /body --type paragraph --prop text="Hello"` |
| `remove` / `move` / `swap` | 删除/移动/交换元素 | `officecli remove report.docx '/body/p[4]'` |
| `batch` | 批量原子操作（一个 save 周期） | `officecli batch data.xlsx --commands '[...]'` |
| `validate` | 校验文档 OpenXML 合法性 | `officecli validate report.docx` |

### 第三步：三种文档格式对应元素

- **Word (.docx)**：`paragraph`（段落）、`run`（文本片段）、`table`、`image`、`header`/`footer`、`section`
- **Excel (.xlsx)**：`sheet`、`row`、`col`、`cell`、`chart`、`table`（ListObject）、`pivottable`
- **PPT (.pptx)**：`slide`、`shape`、`picture`、`chart`、`table`、`transition`、`animation`

### 第四步：性能与文件锁

- 首次调用自动开启 **resident 常驻模式**（60s 空闲超时），避免频繁文件 I/O 和锁冲突
- 修改完后**不需要中间保存**，officecli 自己的 `get`/`query`/`view` 总是能看到最新内容
- 只有在非 officecli 程序（Word/WPS/python-docx 等）要读取文件前，才执行 `officecli close <file>` 或 `officecli save <file>`

### 第五步：输出格式
所有可能返回复杂数据的命令都加上 `--json` 参数，方便 Agent 解析：
```bash
officecli get data.xlsx /Sheet1 --json
officecli batch data.xlsx --commands '[...]' --json
```

## 核心示例

### 创建包含姓名和年龄的 Excel 表格
```bash
# 方式一：逐条 set
officecli create people.xlsx
officecli set people.xlsx /Sheet1/A1 --prop value="姓名"
officecli set people.xlsx /Sheet1/B1 --prop value="年龄"
officecli set people.xlsx /Sheet1/A2 --prop value="Alice"
officecli set people.xlsx /Sheet1/B2 --prop value="28"

# 方式二：batch 一次性（原子操作）
echo '[
  {"command":"set","path":"/Sheet1/A1","props":{"value":"姓名","bold":"true"}},
  {"command":"set","path":"/Sheet1/B1","props":{"value":"年龄","bold":"true"}},
  {"command":"set","path":"/Sheet1/A2","props":{"value":"Alice"}},
  {"command":"set","path":"/Sheet1/B2","props":{"value":"28"}}
]' | officecli batch people.xlsx --json
```

### 创建 Word 报告
```bash
officecli create report.docx
officecli add report.docx /body --type paragraph --prop text="季度总结" --prop style=Heading1
officecli add report.docx /body --type paragraph --prop text="本季度营收增长 25%..."
officecli close report.docx
```

### 创建 PPT 幻灯片
```bash
officecli create slides.pptx
officecli add slides.pptx / --type slide --prop title="Q4 Report"
officecli add slides.pptx '/slide[1]' --type shape --prop text="Revenue grew 25%" --prop x=2cm --prop y=5cm --prop size=24
officecli close slides.pptx
```

## 常见陷阱
- 属性名不要写 `--name "foo"`，全部走 `--prop name="foo"`
- XPath 路径 `[N]` 要用引号包住，防止 shell glob 展开
- PPT `shape[1]` 通常是标题占位符，内容形状从 `shape[2]` 开始
- 路径是 **1-based** XPath 约定，`set --index` 是 **0-based** 数组约定，Excel 的 `add row/col` 又是 **1-based**
- 修改完别忘了 `validate` 或 `view issues` 检查合法性

## 辅助文件
- `office_cli_manual.md`：完整命令手册。遇到不确定的属性名或命令语法时，先 loadSkill 读取这个文件。
