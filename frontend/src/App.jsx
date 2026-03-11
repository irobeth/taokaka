import React, { useEffect, useRef, useState, useCallback } from 'react'

const WS_URL = 'ws://localhost:1979/ws/state'
const SEVERITY_LABELS = { 1: 'PG-13', 2: 'R', 3: 'NC-17', 4: '4chan' }

// ── Utility Components ──

function Dot({ on, warn }) {
  return <span className={`dot ${warn ? 'warn' : on ? 'on' : 'off'}`} />
}

function SignalRow({ label, value, active }) {
  const display = typeof value === 'boolean' ? (value ? 'YES' : 'no') : value
  return (
    <div className="signal-row">
      <span className="signal-label">{label}</span>
      <span className={`signal-value ${active ? 'active' : 'inactive'}`}>{display}</span>
    </div>
  )
}

function Panel({ title, children, className = '', subtitle }) {
  return (
    <div className={`panel ${className}`}>
      <div className="panel-title">
        {title}
        {subtitle && <span className="panel-subtitle">{subtitle}</span>}
      </div>
      <div className="panel-body">{children}</div>
    </div>
  )
}

function ToggleButton({ label, on, onClick, color, disabled }) {
  return (
    <button
      className={`toggle-btn ${on ? 'toggle-on' : 'toggle-off'}`}
      onClick={onClick}
      disabled={disabled}
      style={on ? { borderColor: color, color } : {}}
    >
      <Dot on={on} /> {label}
    </button>
  )
}

// ── Backend Launcher (inline in header) ──

function BackendLauncher({ onLog }) {
  const [launching, setLaunching] = useState(false)
  const [error, setError] = useState(null)
  const pollRef = useRef(null)

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  const startBackend = async () => {
    setLaunching(true)
    setError(null)
    onLog('Starting Taokaka backend...')

    try {
      const res = await fetch('/api/start-backend', { method: 'POST' })
      const data = await res.json()

      if (data.error) {
        setError(data.error)
        onLog(`Error: ${data.error}`)
        setLaunching(false)
        return
      }

      if (data.status === 'already_running') {
        onLog(`Already running (PID ${data.pid})`)
      } else {
        onLog(`Process started (PID ${data.pid})`)
      }

      let prevLen = 0
      pollRef.current = setInterval(async () => {
        try {
          const statusRes = await fetch('/api/backend-status')
          const status = await statusRes.json()
          if (status.logs?.length > prevLen) {
            for (let i = prevLen; i < status.logs.length; i++) {
              onLog(status.logs[i].trimEnd())
            }
            prevLen = status.logs.length
          }
          if (!status.running) {
            clearInterval(pollRef.current)
            setLaunching(false)
            onLog('Backend process exited.')
          }
        } catch {}
      }, 1000)
    } catch (err) {
      setError(`Could not reach launcher API: ${err.message}`)
      onLog(`Error: Could not reach launcher API: ${err.message}`)
      setLaunching(false)
    }
  }

  const stopBackend = async () => {
    try {
      await fetch('/api/stop-backend', { method: 'POST' })
      setLaunching(false)
      onLog('Backend stopped.')
      if (pollRef.current) clearInterval(pollRef.current)
    } catch {}
  }

  return (
    <div className="backend-launcher">
      {!launching ? (
        <button className="start-btn" onClick={startBackend}>Start Backend</button>
      ) : (
        <button className="stop-btn" onClick={stopBackend}>Stop</button>
      )}
      {error && <span className="launcher-error">{error}</span>}
    </div>
  )
}

// ── Header ──

function Header({ state, connected, sendCmd, onLog }) {
  const r = state?.readiness || {}
  const p = state?.pipeline || {}
  const tog = state?.toggles || {}
  const t = state?.timing || {}
  const alertness = state?.alertness || 'asleep'
  const rating = state?.profanity_rating || 2

  const patience = t.patience || 60
  const elapsed = t.seconds_since_last || 0
  const pct = Math.min(elapsed / patience, 1)
  const barColor = pct < 0.5 ? '#4caf50' : pct < 0.8 ? '#ff9800' : '#f44336'

  const alertnessDisplay = alertness === 'awake'
    ? { text: 'AWAKE', color: '#4caf50' }
    : alertness === 'napping'
      ? { text: 'napping zzz', color: '#ff9800' }
      : { text: 'asleep', color: '#555' }

  return (
    <div className="header">
      <div className="header-top">
        <h1>TAOKAKA</h1>
        <div className="indicators">
          {connected ? (
            <>
              <span><Dot on={r.stt_ready} /> STT {!tog.stt_enabled && <span className="badge badge-off">OFF</span>}</span>
              <span><Dot on={r.tts_ready} /> TTS {!tog.tts_enabled && <span className="badge badge-off">OFF</span>}</span>
              <span><Dot on={state?.discord?.connected} /> Discord</span>
              <span className="sep">|</span>
              <span>Mode: <b style={{ color: p.audio_mode === 'local' ? '#4caf50' : '#ff9800' }}>{p.audio_mode}</b></span>
              <span>Engine: <b style={{ color: '#00bcd4' }}>{r.tts_engine}</b></span>
              <span>Rating: <b style={{ color: '#ff9800' }}>{SEVERITY_LABELS[rating] || rating}</b></span>
              <span className="sep">|</span>
              <span style={{ color: alertnessDisplay.color, fontWeight: 700 }}>{alertnessDisplay.text}</span>
              <span className="sep">|</span>
            </>
          ) : (
            <BackendLauncher onLog={onLog} />
          )}
          <span className={`connection ${connected ? 'connected' : 'disconnected'}`}>
            <Dot on={connected} /> {connected ? 'Live' : 'Disconnected'}
          </span>
          {connected && (
            <button className="action-btn shutdown" onClick={() => {
              if (window.confirm('Shut down Taokaka backend?'))
                sendCmd({ cmd: 'shutdown' })
            }}>Shutdown</button>
          )}
        </div>
      </div>
      {connected && (
        <div className="header-controls">
          <ToggleButton label="STT" on={tog.stt_enabled} onClick={() => sendCmd({ cmd: 'toggle_stt' })} color="#4caf50" />
          <ToggleButton label="TTS" on={tog.tts_enabled} onClick={() => sendCmd({ cmd: 'toggle_tts' })} color="#4caf50" />
          <ToggleButton label="LLM" on={tog.llm_enabled} onClick={() => sendCmd({ cmd: 'toggle_llm' })} color="#4caf50" />
          <ToggleButton
            label={p.audio_mode === 'local' ? 'Local' : 'Discord'}
            on={true}
            onClick={() => sendCmd({ cmd: 'toggle_audio_mode' })}
            color={p.audio_mode === 'local' ? '#4caf50' : '#ff9800'}
          />
          <span className="sep">|</span>
          <button className="action-btn cancel" onClick={() => sendCmd({ cmd: 'cancel_next' })}>Cancel</button>
          <button className="action-btn abort" onClick={() => sendCmd({ cmd: 'abort_tts' })}>Stop TTS</button>
          <button className="action-btn nuke" onClick={() => {
            if (window.confirm('Clear all conversation history?')) sendCmd({ cmd: 'nuke_history' })
          }}>Clear History</button>
          <button className="action-btn factory-reset" onClick={() => {
            if (window.confirm('\u26a0\ufe0f FACTORY RESET \u2014 Wipe ALL memories, curiosities, and history? This cannot be undone!'))
              sendCmd({ cmd: 'factory_reset' })
          }}>Factory Reset</button>
        </div>
      )}
      <div className="attention-bar-container">
        <div className="attention-bar" style={{ width: `${connected ? (1 - pct) * 100 : 0}%`, background: barColor }} />
        {connected && <span className="attention-label">{Math.max(0, Math.round(patience - elapsed))}s</span>}
      </div>
    </div>
  )
}

// ── Control Bar ──

function ChatInput({ sendCmd, connected }) {
  const [text, setText] = useState('')

  const submit = useCallback(() => {
    if (text.trim()) {
      sendCmd({ cmd: 'send_message', text: text.trim() })
      setText('')
    }
  }, [text, sendCmd])

  return (
    <div className={`chat-input-bar ${!connected ? 'disabled' : ''}`}>
      <input
        type="text"
        placeholder={connected ? 'Talk to Tao...' : 'Backend offline...'}
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') submit() }}
        disabled={!connected}
      />
      <button className="send-btn" onClick={submit} disabled={!connected}>Send</button>
    </div>
  )
}

// ── Panels ──

function StatusPanel({ state }) {
  const p = state?.pipeline || {}
  const w = state?.stt_workers || []
  return (
    <Panel title="Status">
      <SignalRow label="Human" value={p.human_speaking} active={p.human_speaking} />
      <SignalRow label="Thinking" value={p.AI_thinking} active={p.AI_thinking} />
      <SignalRow label="Speaking" value={p.AI_speaking} active={p.AI_speaking} />
      <SignalRow label="Voice User" value={p.active_voice_user || '\u2014'} active={!!p.active_voice_user} />
      {w.length > 0 && (
        <>
          <div className="section-label">STT Recorders</div>
          {w.map((s, i) => (
            <SignalRow key={i} label={s.name} value={s.status} active={s.status === 'speaking'} />
          ))}
        </>
      )}
    </Panel>
  )
}

function PipelinePanel({ state }) {
  const p = state?.pipeline || {}
  const t = state?.timing || {}
  const q = state?.chat_queues || {}
  const ext = state?.extractor_signals || {}
  return (
    <Panel title="Pipeline">
      <SignalRow label="new_message" value={p.new_message} active={p.new_message} />
      <SignalRow label="patience" value={`${t.seconds_since_last || 0}s / ${t.patience}s`} active={t.seconds_since_last > t.patience} />
      <SignalRow label="twitch queue" value={q.twitch || 0} active={q.twitch > 0} />
      <SignalRow label="discord queue" value={q.discord || 0} active={q.discord > 0} />
      <div className="section-label">Extractor Signals</div>
      {Object.keys(ext).length === 0 && <div style={{ color: '#555', padding: '4px 0' }}>[none]</div>}
      {Object.entries(ext).map(([key, val]) => {
        const display = Array.isArray(val)
          ? val.slice(0, 8).join(', ') + (val.length > 8 ? ` (+${val.length - 8})` : '')
          : String(val).slice(0, 120)
        return <SignalRow key={key} label={key} value={display} active={false} />
      })}
    </Panel>
  )
}

function OnlinePanel({ state }) {
  const d = state?.discord || {}
  return (
    <Panel title="Online">
      {!d.connected && <div style={{ color: '#555' }}>Not in a voice channel</div>}
      {d.connected && (!d.members || d.members.length === 0) && <div style={{ color: '#555' }}>No one here</div>}
      {d.members?.map((m) => (
        <div key={m.id} className="member"><Dot on /> {m.name}</div>
      ))}
    </Panel>
  )
}

function ConversationPanel({ state }) {
  const ref = useRef(null)
  const history = state?.history || []

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [history.length])

  return (
    <Panel title="Conversation" className="grow">
      <div ref={ref} style={{ overflow: 'auto', flex: 1 }}>
        {history.length === 0 && <div style={{ color: '#555', padding: '12px 0' }}>No messages yet...</div>}
        {history.map((msg, i) => {
          const ts = msg.timestamp ? new Date(msg.timestamp * 1000).toLocaleTimeString() : ''
          const isAI = msg.role === 'assistant'
          let speaker = isAI ? 'Taokaka' : 'User'
          let content = msg.content
          if (!isAI && content.includes(': ')) {
            const colonIdx = content.indexOf(': ')
            speaker = content.slice(0, colonIdx)
            content = content.slice(colonIdx + 2)
          }
          return (
            <div key={i} className="msg">
              <span className="ts">{ts}</span>
              <span className={`role ${msg.role}`}>{speaker}</span>
              <span className="content">{content}</span>
            </div>
          )
        })}
      </div>
    </Panel>
  )
}

const LOG_LEVEL_COLORS = {
  info: '#00bcd4',
  warn: '#ff9800',
  error: '#f44336',
  debug: '#666',
}

function LogsPanel({ state, startupLogs }) {
  const ref = useRef(null)
  const entries = state?.log_entries || []
  const allEntries = [
    ...startupLogs.map(msg => ({ ts: '', source: 'Startup', msg, level: 'info' })),
    ...entries,
  ]

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [allEntries.length])

  return (
    <Panel title="Logs" className="grow">
      <div ref={ref} style={{ overflow: 'auto', flex: 1 }}>
        {allEntries.length === 0 && <div style={{ color: '#555', padding: '12px 0' }}>No logs yet...</div>}
        {allEntries.map((e, i) => (
          <div key={i} className="log-entry" style={{ color: LOG_LEVEL_COLORS[e.level] || '#aaa' }}>
            {e.ts && <span className="ts">{e.ts}</span>}
            {e.source && <span className="log-source">[{e.source}]</span>}
            <span>{e.msg}</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function ThoughtsPanel({ state, onSelect }) {
  const ref = useRef(null)
  const thoughts = state?.recent_thoughts || []

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [thoughts.length])

  return (
    <Panel title="Thoughts">
      <div ref={ref} style={{ overflow: 'auto', flex: 1 }}>
        {thoughts.length === 0 && <div style={{ color: '#555' }}>No thoughts yet...</div>}
        {thoughts.map((t, i) => {
          const ts = t.timestamp ? new Date(t.timestamp * 1000).toLocaleTimeString() : ''
          return (
            <div key={i} className="thought clickable" onClick={() => onSelect && onSelect(t)}>
              <span className="ts">{ts}</span>
              <span className="thought-text">{t.thought}</span>
            </div>
          )
        })}
      </div>
    </Panel>
  )
}

function ZeitgeistPanel({ state }) {
  const z = state?.zeitgeist || ''
  const kw = state?.extractor_signals?.keywords || []
  return (
    <Panel title="Zeitgeist">
      {z ? <div className="zeitgeist-text">{z}</div> : <div style={{ color: '#555' }}>Waiting for enough conversation...</div>}
      {kw.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div className="keyword-list">
            {kw.slice(0, 15).map((k, i) => <span key={i} className="keyword">{k}</span>)}
          </div>
        </div>
      )}
    </Panel>
  )
}

function PromptPanel({ state }) {
  const ref = useRef(null)
  const prompt = state?.last_full_prompt || ''
  const [showRaw, setShowRaw] = useState(false)

  const rawMarker = '\u2550\u2550\u2550 RAW RESPONSE \u2550\u2550\u2550'
  const markerIdx = prompt.indexOf(rawMarker)
  const promptOnly = markerIdx >= 0 ? prompt.slice(0, markerIdx) : prompt
  const displayText = showRaw ? prompt : promptOnly

  return (
    <Panel
      title="Last Prompt"
      subtitle={
        <button className="toggle-raw-btn" onClick={() => setShowRaw(!showRaw)}>
          {showRaw ? 'Hide Raw' : 'Show Raw'}
        </button>
      }
    >
      <div ref={ref} style={{ overflow: 'auto', flex: 1 }}>
        <pre className="prompt-text">{displayText || '[no prompt yet]'}</pre>
      </div>
    </Panel>
  )
}

function MemoryTreePanel({ state, sendCmd, connected, onSelect }) {
  const mem = state?.memories || {}
  const all = mem.all || []
  const forcedIds = new Set(mem.forced_ids || [])
  const [filter, setFilter] = useState('')

  const groups = {}
  const typeOrder = ['core', 'personal', 'nickname', 'about_user', 'opinion', 'definition', 'long_term', 'short_term', 'mood', 'reflection']
  all.forEach(m => {
    const type = m.type || 'unknown'
    if (!groups[type]) groups[type] = []
    groups[type].push(m)
  })

  const matchesFilter = (m) => {
    if (!filter) return true
    const f = filter.toLowerCase()
    return (m.document || '').toLowerCase().includes(f)
      || (m.title || '').toLowerCase().includes(f)
      || (m.keywords || '').toLowerCase().includes(f)
      || (m.related_user || '').toLowerCase().includes(f)
  }

  const orderedTypes = [...typeOrder.filter(t => groups[t]), ...Object.keys(groups).filter(t => !typeOrder.includes(t))]

  return (
    <Panel title={`Memory Tree (${mem.total || 0})`} className="grow">
      <input
        type="text"
        placeholder="Filter memories..."
        value={filter}
        onChange={e => setFilter(e.target.value)}
        className="filter-input"
      />
      <div style={{ overflow: 'auto', flex: 1 }}>
        {all.length === 0 && <div style={{ color: '#555', padding: '12px 0' }}>No memories loaded</div>}
        {orderedTypes.map(type => {
          const items = groups[type].filter(matchesFilter)
          if (items.length === 0) return null
          return (
            <div key={type} className="memory-group">
              <div className="memory-type-header">{type} ({items.length})</div>
              {items.map(m => {
                const forced = forcedIds.has(m.id)
                return (
                  <div key={m.id} className={`memory-tree-item ${forced ? 'forced' : ''}`}>
                    <div className="memory-tree-content clickable" onClick={() => onSelect && onSelect(m)}>
                      {forced && <span className="forced-badge">[F]</span>}
                      {m.related_user && m.related_user !== 'personal' && (
                        <span className="user-tag">@{m.related_user}</span>
                      )}
                      {m.title && <span className="memory-title-inline">{m.title}: </span>}
                      <span className="memory-doc-text">{m.document}</span>
                    </div>
                    <div className="memory-tree-actions">
                      <button
                        className={`mem-btn ${forced ? 'unpin' : 'pin'}`}
                        onClick={() => sendCmd({ cmd: 'force_memory', id: m.id })}
                        title={forced ? 'Unpin' : 'Pin to prompt'}
                        disabled={!connected}
                      >
                        {forced ? 'unpin' : 'pin'}
                      </button>
                      <button
                        className="mem-btn delete"
                        onClick={() => {
                          if (window.confirm(`Delete memory?\n\n${m.document.slice(0, 100)}`))
                            sendCmd({ cmd: 'delete_memory', id: m.id })
                        }}
                        title="Delete"
                        disabled={!connected}
                      >
                        del
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
    </Panel>
  )
}

function RecalledPanel({ state }) {
  const mem = state?.memories || {}
  const curiosities = state?.extractor_signals?.curiosities || []
  return (
    <Panel title="Recalled">
      {(mem.recalled || []).length === 0 && <div style={{ color: '#555' }}>none yet</div>}
      {(mem.recalled || []).map((doc, i) => (
        <div key={i} className="recalled-item">{doc}</div>
      ))}
      {(mem.forced_ids || []).length > 0 && (
        <>
          <div className="section-label">Forced</div>
          {mem.forced_ids.map((id, i) => {
            const m = (mem.all || []).find(x => x.id === id)
            return m ? <div key={i} className="recalled-item forced-recall">{m.document}</div> : null
          })}
        </>
      )}
      {curiosities.length > 0 && (
        <>
          <div className="section-label">Curiosities</div>
          {curiosities.slice(0, 5).map((c, i) => (
            <div key={i} className="curiosity-item">? {typeof c === 'string' ? c : c.question || JSON.stringify(c)}</div>
          ))}
        </>
      )}
      {(mem.recent_generated || []).length > 0 && (
        <>
          <div className="section-label">Recently Generated</div>
          {mem.recent_generated.map((doc, i) => (
            <div key={i} className="recalled-item generated">{doc}</div>
          ))}
        </>
      )}
    </Panel>
  )
}

// ── Mood Panel ──

const INTENSITY_LABELS = ['faint', 'mild', 'moderate', 'strong', 'overwhelming']

function MoodPanel({ state }) {
  const mood = state?.extractor_signals?.mood || {}
  const subjects = state?.extractor_signals?.subject_moods || {}

  const intensityLabel = (v) => {
    if (v >= 0.8) return INTENSITY_LABELS[4]
    if (v >= 0.6) return INTENSITY_LABELS[3]
    if (v >= 0.4) return INTENSITY_LABELS[2]
    if (v >= 0.2) return INTENSITY_LABELS[1]
    return INTENSITY_LABELS[0]
  }

  const intensityBar = (v) => {
    const pct = Math.round((v || 0) * 100)
    const color = v >= 0.7 ? '#f44336' : v >= 0.4 ? '#ff9800' : '#4caf50'
    return (
      <div className="mood-bar-track">
        <div className="mood-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    )
  }

  return (
    <Panel title="Mood">
      {!mood.emotion ? (
        <div style={{ color: '#555' }}>No mood data yet...</div>
      ) : (
        <>
          <div className="mood-overall">
            <span className="mood-emoji-big">{mood.emoji || ''}</span>
            <div className="mood-overall-info">
              <div className="mood-emotion">{mood.emotion}</div>
              <div className="mood-intensity-row">
                {intensityBar(mood.intensity)}
                <span className="mood-intensity-label">{intensityLabel(mood.intensity)} ({Math.round((mood.intensity || 0) * 100)}%)</span>
              </div>
              <div className="mood-meta">inertia: {Math.round((mood.inertia || 0) * 100)}%</div>
            </div>
          </div>
          {mood.summary && <div className="mood-summary">{mood.summary}</div>}
          {mood.shift && <div className="mood-shift">{mood.shift}</div>}
        </>
      )}
      {Object.keys(subjects).length > 0 && (
        <>
          <div className="section-label" style={{ marginTop: 12 }}>Subject Feelings</div>
          {Object.entries(subjects).map(([name, sm]) => (
            <div key={name} className="mood-subject">
              <span className="mood-subject-emoji">{sm.emoji || ''}</span>
              <div className="mood-subject-info">
                <div className="mood-subject-name">{name}</div>
                <div className="mood-subject-emotion">{sm.emotion} ({Math.round((sm.intensity || 0) * 100)}%)</div>
                {sm.reason && <div className="mood-subject-reason">{sm.reason}</div>}
              </div>
              {intensityBar(sm.intensity)}
            </div>
          ))}
        </>
      )}
    </Panel>
  )
}

// ── Details Panel ──

function DetailsPanel({ detail }) {
  if (!detail) {
    return (
      <Panel title="Details" className="grow">
        <div style={{ color: '#555', padding: '12px 0' }}>Click a memory or thought to view details here.</div>
      </Panel>
    )
  }

  if (detail.type === 'memory') {
    const m = detail.data
    return (
      <Panel title="Memory Details" className="grow">
        <div className="detail-section">
          <div className="detail-label">Document</div>
          <div className="detail-value">{m.document}</div>
        </div>
        {m.title && (
          <div className="detail-section">
            <div className="detail-label">Title</div>
            <div className="detail-value">{m.title}</div>
          </div>
        )}
        <div className="detail-section">
          <div className="detail-label">Type</div>
          <div className="detail-value">{m.type || 'unknown'}</div>
        </div>
        {m.related_user && (
          <div className="detail-section">
            <div className="detail-label">Related User</div>
            <div className="detail-value">@{m.related_user}</div>
          </div>
        )}
        {m.keywords && (
          <div className="detail-section">
            <div className="detail-label">Keywords</div>
            <div className="keyword-list">{m.keywords.split(',').map((k, i) => <span key={i} className="keyword">{k.trim()}</span>)}</div>
          </div>
        )}
        <div className="detail-section">
          <div className="detail-label">ID</div>
          <div className="detail-value detail-id">{m.id}</div>
        </div>
      </Panel>
    )
  }

  if (detail.type === 'thought') {
    const t = detail.data
    const ts = t.timestamp ? new Date(t.timestamp * 1000).toLocaleString() : ''
    return (
      <Panel title="Thought Details" className="grow">
        <div className="detail-section">
          <div className="detail-label">Thought</div>
          <div className="detail-value">{t.thought}</div>
        </div>
        {ts && (
          <div className="detail-section">
            <div className="detail-label">Time</div>
            <div className="detail-value">{ts}</div>
          </div>
        )}
      </Panel>
    )
  }

  return <Panel title="Details" className="grow"><div style={{ color: '#555' }}>Unknown detail type</div></Panel>
}

// ── App ──

const LEFT_TABS = [
  { id: 'memories', label: 'Memories' },
  { id: 'recalled', label: 'Recalled' },
  { id: 'thoughts', label: 'Thoughts' },
  { id: 'zeitgeist', label: 'Zeitgeist' },
  { id: 'mood', label: 'Mood' },
  { id: 'prompt', label: 'Prompt' },
  { id: 'pipeline', label: 'Pipeline' },
]

export default function App() {
  const [state, setState] = useState(null)
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)
  const [leftTab, setLeftTab] = useState('memories')
  const [chatTab, setChatTab] = useState('chat')
  const [detail, setDetail] = useState(null)
  const [startupLogs, setStartupLogs] = useState([])

  const addStartupLog = useCallback((msg) => {
    setStartupLogs(prev => [...prev, msg])
    setChatTab('logs')
  }, [])

  useEffect(() => {
    let reconnectTimer
    function connect() {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws
      ws.onopen = () => setConnected(true)
      ws.onclose = () => {
        setConnected(false)
        reconnectTimer = setTimeout(connect, 2000)
      }
      ws.onerror = () => ws.close()
      ws.onmessage = (e) => {
        try { setState(JSON.parse(e.data)) } catch {}
      }
    }
    connect()
    return () => {
      clearTimeout(reconnectTimer)
      wsRef.current?.close()
    }
  }, [])

  const sendCmd = useCallback((cmd) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(cmd))
    }
  }, [])

  const showDetail = useCallback((type, data) => {
    setDetail({ type, data })
    setChatTab('details')
  }, [])

  return (
    <div className="dashboard">
      <Header state={state} connected={connected} sendCmd={sendCmd} onLog={addStartupLog} />
      <div className="columns">
        <div className="left-col">
          <div className="left-tabs">
            {LEFT_TABS.map(t => (
              <button
                key={t.id}
                className={`tab ${leftTab === t.id ? 'active' : ''}`}
                onClick={() => setLeftTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="left-pane">
            {leftTab === 'memories' && <MemoryTreePanel state={state} sendCmd={sendCmd} connected={connected} onSelect={(m) => showDetail('memory', m)} />}
            {leftTab === 'recalled' && <RecalledPanel state={state} />}
            {leftTab === 'thoughts' && <ThoughtsPanel state={state} onSelect={(t) => showDetail('thought', t)} />}
            {leftTab === 'zeitgeist' && <ZeitgeistPanel state={state} />}
            {leftTab === 'mood' && <MoodPanel state={state} />}
            {leftTab === 'prompt' && <PromptPanel state={state} />}
            {leftTab === 'pipeline' && <PipelinePanel state={state} />}
          </div>
        </div>
        <div className="center-col">
          <div className="chat-tabs">
            <button className={`tab ${chatTab === 'chat' ? 'active' : ''}`} onClick={() => setChatTab('chat')}>Chat</button>
            <button className={`tab ${chatTab === 'logs' ? 'active' : ''}`} onClick={() => setChatTab('logs')}>Logs</button>
            <button className={`tab ${chatTab === 'details' ? 'active' : ''}`} onClick={() => setChatTab('details')}>
              Details{detail ? ' *' : ''}
            </button>
          </div>
          <div className="chat-pane">
            {chatTab === 'chat' && <ConversationPanel state={state} />}
            {chatTab === 'logs' && <LogsPanel state={state} startupLogs={startupLogs} />}
            {chatTab === 'details' && <DetailsPanel detail={detail} />}
          </div>
        </div>
        <div className="right-col">
          <StatusPanel state={state} />
          <OnlinePanel state={state} />
        </div>
      </div>
      <ChatInput sendCmd={sendCmd} connected={connected} />
    </div>
  )
}
