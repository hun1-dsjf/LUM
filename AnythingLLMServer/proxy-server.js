/**
 * AnythingLLM 本地代理服务器
 *
 * 作用：把 /api/* 请求原样转发到 AnythingLLM，并在服务端附加 Authorization 头。
 * API Key 只存在于服务端环境变量（.env）中，前端代码不再接触任何密钥。
 *
 * 运行步骤：
 *   1. npm install
 *   2. 复制 .env.example 为 .env，填入真实 Key
 *   3. node proxy-server.js
 *   4. 浏览器打开 http://localhost:8787/upload.html
 *
 * 注意：端口用 8787 —— 3001 是 AnythingLLM 本身的端口，不能再用。
 */

require('dotenv').config();

const express = require('express');
const http = require('http');
const https = require('https');
const { URL } = require('url');
const path = require('path');

const BASE = process.env.ANYTHINGLLM_BASE || 'http://localhost:3001';
const API_KEY = process.env.ANYTHINGLLM_API_KEY || '';
const PORT = Number(process.env.PROXY_PORT || 8787);

if (!API_KEY) {
  console.error('缺少环境变量 ANYTHINGLLM_API_KEY：请复制 .env.example 为 .env 并填入真实 Key。');
  process.exit(1);
}

const app = express();

// 允许浏览器直接打开本地 HTML 文件（file://）时跨域调用代理
app.use((req, res, next) => {
  res.set('Access-Control-Allow-Origin', '*');
  next();
});

// 托管同目录静态页面；dotfiles:'deny' 确保 .env 永远无法被 HTTP 访问
app.use(express.static(__dirname, { dotfiles: 'deny' }));

// 通用转发：保留原始方法、路径、Content-Type（含 multipart 表单）和请求体流
app.use('/api', (req, res) => {
  const target = new URL('/api' + req.url, BASE);
  const mod = target.protocol === 'https:' ? https : http;
  const headers = { ...req.headers, host: target.host, authorization: 'Bearer ' + API_KEY };

  const upstream = mod.request(target, { method: req.method, headers }, (up) => {
    res.writeHead(up.statusCode, up.headers);
    up.pipe(res);
  });
  upstream.on('error', (e) =>
    res.status(502).json({ error: '无法连接 AnythingLLM (' + BASE + '): ' + e.message })
  );
  req.pipe(upstream); // 请求体（multipart / JSON）原样透传
});

app.listen(PORT, () => {
  console.log('代理已启动: http://localhost:' + PORT + '  ->  ' + BASE);
  console.log('打开 http://localhost:' + PORT + '/upload.html 开始使用');
});
