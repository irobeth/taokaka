import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { spawn } from 'child_process'
import path from 'path'

// Track backend process so we don't spawn multiples
let backendProc = null

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'backend-launcher',
      configureServer(server) {
        // POST /api/start-backend — launches start.sh from the project root
        server.middlewares.use('/api/start-backend', (req, res) => {
          if (req.method !== 'POST') {
            res.statusCode = 405
            res.end(JSON.stringify({ error: 'POST only' }))
            return
          }

          if (backendProc && !backendProc.killed) {
            res.statusCode = 200
            res.end(JSON.stringify({ status: 'already_running', pid: backendProc.pid }))
            return
          }

          const projectRoot = path.resolve(__dirname, '..')
          const startScript = path.join(projectRoot, 'start.sh')

          try {
            backendProc = spawn('bash', [startScript], {
              cwd: projectRoot,
              stdio: 'pipe',
              detached: false,
            })

            // Collect output for status checks
            const logs = []
            const pushLog = (data) => {
              const line = data.toString()
              logs.push(line)
              if (logs.length > 200) logs.shift()
            }
            backendProc.stdout.on('data', pushLog)
            backendProc.stderr.on('data', pushLog)

            backendProc.on('close', (code) => {
              console.log(`[backend] exited with code ${code}`)
              backendProc = null
            })

            // Attach logs to process for status endpoint
            backendProc._logs = logs

            res.statusCode = 200
            res.end(JSON.stringify({ status: 'started', pid: backendProc.pid }))
          } catch (err) {
            res.statusCode = 500
            res.end(JSON.stringify({ error: err.message }))
          }
        })

        // GET /api/backend-status — check if backend is running + recent logs
        server.middlewares.use('/api/backend-status', (req, res) => {
          if (req.method !== 'GET') {
            res.statusCode = 405
            res.end(JSON.stringify({ error: 'GET only' }))
            return
          }

          const running = backendProc && !backendProc.killed
          const logs = running ? (backendProc._logs || []).slice(-50) : []

          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({
            running,
            pid: running ? backendProc.pid : null,
            logs,
          }))
        })

        // POST /api/stop-backend — kill backend process
        server.middlewares.use('/api/stop-backend', (req, res) => {
          if (req.method !== 'POST') {
            res.statusCode = 405
            res.end(JSON.stringify({ error: 'POST only' }))
            return
          }

          if (backendProc && !backendProc.killed) {
            backendProc.kill('SIGTERM')
            res.end(JSON.stringify({ status: 'stopped' }))
          } else {
            res.end(JSON.stringify({ status: 'not_running' }))
          }
        })
      },
    },
  ],
  server: { port: 3000 },
})
