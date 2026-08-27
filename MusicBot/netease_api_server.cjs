#!/usr/bin/env node

/*
 * MusicBot 内置的网易云 API 入口。
 *
 * api-enhanced 是 Node.js 模块，而 MusicBot 后端是 Python。这里仅在本机
 * 127.0.0.1 上启动它的 HTTP server，作为两个运行时之间的稳定边界。
 * 该端口不应交给 Nginx，也不应监听公网地址。
 */

const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const host = process.env.NETEASE_API_HOST || '127.0.0.1'
const port = Number.parseInt(process.env.NETEASE_API_PORT || '8005', 10)

if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error(`NETEASE_API_PORT 无效: ${process.env.NETEASE_API_PORT}`)
}

async function start() {
  // api-enhanced 会用 dotenv 读取当前目录的 .env。切换到依赖目录，防止它
  // 误读 MusicBot/.env 中的 KOOK Token、管理密钥等无关凭证。
  const packageRoot = path.dirname(
    require.resolve('@neteasecloudmusicapienhanced/api/package.json'),
  )
  process.chdir(packageRoot)

  const anonymousTokenPath = path.resolve(os.tmpdir(), 'anonymous_token')
  if (!fs.existsSync(anonymousTokenPath)) {
    fs.writeFileSync(anonymousTokenPath, '', 'utf8')
  }

  const generateConfig = require('@neteasecloudmusicapienhanced/api/generateConfig')
  const { serveNcmApi } = require('@neteasecloudmusicapienhanced/api/server')

  await generateConfig()
  await serveNcmApi({
    host,
    port,
    // MusicBot 锁定 package-lock 版本，不需要每次启动再访问外网检查版本。
    checkVersion: false,
  })
}

start().catch((error) => {
  console.error('[netease-api] 启动失败', error)
  process.exitCode = 1
})
