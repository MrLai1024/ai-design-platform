// src/server.js
// node-compiler HTTP service — POST /compile {project_root, full, entry}
// → {ok, errors:[{file,line,column,message,source}]}
import { createServer } from 'node:http'
import { compileProject } from './compile.js'

const PORT = Number(process.env.PORT || 5199)

const server = createServer(async (req, res) => {
  // CORS for local dev (gateway calls server-to-server; browsers only during
  // manual debugging).
  res.setHeader('Access-Control-Allow-Origin', '*')
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS')
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type')

  if (req.method === 'OPTIONS') {
    res.writeHead(204)
    res.end()
    return
  }

  if (req.method !== 'POST') {
    res.writeHead(405, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ ok: false, error: 'Method not allowed' }))
    return
  }

  let body = ''
  req.on('data', (chunk) => { body += chunk })
  req.on('end', async () => {
    let payload
    try {
      payload = JSON.parse(body || '{}')
    } catch {
      res.writeHead(400, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ ok: false, error: 'Invalid JSON body' }))
      return
    }

    const projectRoot = payload.project_root || payload.projectRoot
    if (!projectRoot) {
      res.writeHead(400, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ ok: false, error: 'Missing project_root' }))
      return
    }

    try {
      const result = await compileProject(projectRoot, {
        full: Boolean(payload.full),
        entry: payload.entry || undefined,
      })
      res.writeHead(200, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify(result))
    } catch (e) {
      res.writeHead(500, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({
        ok: false,
        errors: [{ file: '', line: 0, column: 0, message: String(e?.message || e), source: 'node-compiler' }],
      }))
    }
  })
})

server.listen(PORT, () => {
  console.log(`[node-compiler] listening on :${PORT}`)
})
