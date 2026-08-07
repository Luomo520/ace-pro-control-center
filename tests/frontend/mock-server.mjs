import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { makeStatus } from './fixtures.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const project = path.resolve(here, '../..')
const port = Number(process.env.PORT || 8767)
const contentTypes = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8' }

const status = makeStatus(3, ['ace1', 'ace2', 'ace1'])
status.devices[0].slots[0].loaded = true
status.devices[1].slots[2].remaining_percent = 22
status.devices[2].connected = false

createServer(async (request, response) => {
  if (request.url?.startsWith('/server/ace/status')) {
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify({ ok: true, result: status }))
    return
  }
  if (request.url?.startsWith('/server/ace/action')) {
    response.writeHead(200, { 'Content-Type': 'application/json' })
    response.end(JSON.stringify({ ok: true, result: { accepted: true, transaction_id: 'mock' } }))
    return
  }
  const urlPath = request.url === '/' ? '/ace-v3/' : request.url
  let relative = urlPath.replace(/^\//, '')
  if (urlPath === '/ace-v3/') relative = 'frontend/dashboard/index.html'
  else if (urlPath.startsWith('/ace-v3/')) relative = `frontend/dashboard/${urlPath.slice('/ace-v3/'.length)}`
  else if (urlPath.startsWith('/shared/')) relative = `frontend/shared/${urlPath.slice('/shared/'.length)}`
  const target = path.resolve(project, relative)
  if (!target.startsWith(project)) {
    response.writeHead(403).end()
    return
  }
  try {
    const data = await readFile(target)
    response.writeHead(200, { 'Content-Type': contentTypes[path.extname(target)] || 'application/octet-stream' })
    response.end(data)
  } catch (_) {
    response.writeHead(404).end('Not found')
  }
}).listen(port, '127.0.0.1', () => {
  process.stdout.write(`Ace Pro Control Center mock server: http://127.0.0.1:${port}/ace-v3/\n`)
})
