# AnythingLLM Webpage（文档上传页 + 本地代理）

浏览器端页面真实调用 AnythingLLM API，完成 **“上传文档 → 加入工作区 → 自动向量化”** 的一条完整业务闭环。

## 目录结构

```
AnythingLLMServer/
├── proxy-server.js   # Express 本地反向代理（隐藏 API Key、托管静态页）
├── upload.html       # 上传并向量化的单页前端
├── package.json      # express + dotenv
└── .env.example      # 配置模板
```

## 为什么需要代理

AnythingLLM 的 API Key 不能出现在浏览器代码里（任何人按 F12 就能拿到）。因此：

```
浏览器 upload.html ──(无密钥)──> 本地代理 8787 ──(注入 Bearer Key)──> AnythingLLM 3001
```

- API Key 只存在于服务端 `.env`；
- 前端不包含任何密钥；
- 代理只允许本机 `file://` / `localhost` 来源跨域访问。

## 安装与配置

```bash
cd AnythingLLMServer
npm install
copy .env.example .env
```

`.env` 字段：

| 变量 | 说明 |
|---|---|
| `ANYTHINGLLM_BASE` | AnythingLLM 地址，默认 `http://localhost:3001` |
| `ANYTHINGLLM_API_KEY` | **必填**，AnythingLLM 的 API Key；缺失时代理启动即报错退出 |
| `PROXY_PORT` | 代理端口，默认 `8787`（不能与 AnythingLLM 的 3001 冲突） |

## 启动

```bash
node proxy-server.js
# 或 npm start
```

然后浏览器打开 `http://localhost:8787/upload.html`。

> 也可以直接双击 `upload.html`（`file://`）使用，代理允许 `Origin: null`。

## 使用流程

1. 页面打开时请求 `GET /api/v1/workspaces`，把所有工作区填入「目标工作区」下拉框（默认选中第一个）；
2. 选择本地文件（AnythingLLM 支持 PDF/TXT/MD/DOCX 等）与目标工作区；
3. 点击“上传并嵌入”；
4. 以 `multipart/form-data` 调 `POST /api/v1/document/upload`，附带 `addToWorkspaces=<slug>`；
5. 服务端返回文档信息，AnythingLLM 自动切分并向量化。

三种状态均有明确反馈：

- **加载中**：按钮禁用并显示“上传中…”，结果区提示当前工作区；
- **成功**：绿色结果块显示 HTTP 状态与返回 JSON，提示已提交向量化；
- **失败**：红色结果块显示 `错误: ...`（含 HTTP 状态码与上游返回体）。

## 接口与请求示例

```http
GET  /api/v1/workspaces                    # 由代理转发并注入 Authorization
POST /api/v1/document/upload               # multipart: file + addToWorkspaces
```

```js
const fd = new FormData();
fd.append('file', fileInput.files[0]);
fd.append('addToWorkspaces', slug);
await fetch('http://localhost:8787/api/v1/document/upload', { method: 'POST', body: fd });
```

## 失败场景与排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 代理启动报“缺少 ANYTHINGLLM_API_KEY” | `.env` 未配置 | 复制 `.env.example` 并填入 Key |
| 页面提示 `获取工作区失败：HTTP 401` | Key 无效 | 重新生成 AnythingLLM API Key |
| 页面提示 `HTTP 502 无法连接 AnythingLLM` | AnythingLLM 未启动/端口错 | 先启动 AnythingLLM，核对 `ANYTHINGLLM_BASE` |
| `没有可用的工作区` | AnythingLLM 中无工作区 | 先在 AnythingLLM 新建工作区 |
| 浏览器报 CORS | 从非本地来源访问 | 使用 `localhost:8787` 或本地 `file://` 打开 |

## 安全说明

- 密钥仅在代理进程内使用，`express.static` 设置 `dotfiles: 'deny'`，`.env` 无法通过 HTTP 访问；
- 结果区使用 `textContent` 渲染，上游返回内容不会作为 HTML 执行；
- CORS 白名单限定本机来源；
- `.env` 已被 `.gitignore` 忽略。
