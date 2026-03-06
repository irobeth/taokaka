import React, { useEffect, useRef, useState } from 'react'

const WS_URL = 'ws://localhost:1979/ws/state'

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

function Panel({ title, children, className = '' }) {
  return (
    <div className={`panel ${className}`}>
      <div className="panel-title">{title}</div>
      <div className="panel-body">{children}</div>
    </div>
  )
}

function Header({ state, connected }) {
  const r = state?.readiness || {}
  const p = state?.pipeline || {}
  return (
    <div className="header">
      <h1>TAOKAKA</h1>
      <div className="indicators">
        <span><Dot on={r.stt_ready} /> STT</span>
        <span><Dot on={r.tts_ready} /> TTS</span>
        <span><Dot on={state?.discord?.connected} /> Discord</span>
        <span style={{ color: '#888' }}>|</span>
        <span>Mode: <b style={{ color: p.audio_mode === 'local' ? '#4caf50' : '#ff9800' }}>{p.audio_mode}</b></span>
        <span>Engine: <b style={{ color: '#00bcd4' }}>{r.tts_engine}</b></span>
        <span style={{ color: '#888' }}>|</span>
        <span className={`connection ${connected ? 'connected' : 'disconnected'}`}>
          <Dot on={connected} /> {connected ? 'Live' : 'Disconnected'}
        </span>
      </div>
    </div>
  )
}

function StatusPanel({ state }) {
  const p = state?.pipeline || {}
  const w = state?.stt_workers || []
  return (
    <Panel title="Status">
      <SignalRow label="Human" value={p.human_speaking} active={p.human_speaking} />
      <SignalRow label="Thinking" value={p.AI_thinking} active={p.AI_thinking} />
      <SignalRow label="Speaking" value={p.AI_speaking} active={p.AI_speaking} />
      <SignalRow label="Voice User" value={p.active_voice_user || '—'} active={!!p.active_voice_user} />
      {w.length > 0 && (
        <>
          <div style={{ color: '#666', marginTop: 8, fontSize: 11 }}>STT Recorders</div>
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
      <div style={{ color: '#666', marginTop: 8, fontSize: 11, fontWeight: 700 }}>Extractor Signals</div>
      {Object.keys(ext).length === 0 && <div style={{ color: '#555', padding: '4px 0' }}>[none]</div>}
      {Object.entries(ext).map(([key, val]) => {
        const display = Array.isArray(val) ? val.slice(0, 8).join(', ') + (val.length > 8 ? ` (+${val.length - 8})` : '') : String(val)
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
    <Panel title="Conversation">
      <div ref={ref} style={{ overflow: 'auto', flex: 1 }}>
        {history.map((msg, i) => {
          const ts = msg.timestamp ? new Date(msg.timestamp * 1000).toLocaleTimeString() : ''
          return (
            <div key={i} className="msg">
              <span className="ts">{ts}</span>
              <span className={`role ${msg.role}`}>{msg.role === 'assistant' ? 'Taokaka' : 'User'}</span>
              <span className="content">{msg.content}</span>
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

function MemoriesPanel({ state }) {
  const mem = state?.memories || {}
  const [filter, setFilter] = useState('')
  const all = mem.all || []

  const filtered = filter
    ? all.filter(m =>
        m.document.toLowerCase().includes(filter.toLowerCase()) ||
        m.title?.toLowerCase().includes(filter.toLowerCase()) ||
        m.keywords?.toLowerCase().includes(filter.toLowerCase()) ||
        m.related_user?.toLowerCase().includes(filter.toLowerCase())
      )
    : all

  return (
    <Panel title={`Memories (${mem.total || 0})`}>
      <input
        type="text"
        placeholder="Filter..."
        value={filter}
        onChange={e => setFilter(e.target.value)}
        style={{
          width: '100%',
          background: '#0a0a0f',
          border: '1px solid #2a2a3a',
          borderRadius: 3,
          padding: '4px 8px',
          color: '#ccc',
          fontSize: 12,
          marginBottom: 8,
          fontFamily: 'inherit',
        }}
      />
      <div style={{ overflow: 'auto', flex: 1 }}>
        {filtered.map((m) => (
          <div key={m.id} className="memory-item">
            <div className="memory-meta">
              <span className="type">{m.type}</span>
              {m.related_user && m.related_user !== 'personal' && <span className="user">@{m.related_user}</span>}
              {m.keywords && <span>{m.keywords}</span>}
              {mem.forced_ids?.includes(m.id) && <span style={{ color: '#ff9800' }}>[F]</span>}
            </div>
            {m.title && <div className="memory-title">{m.title}</div>}
            <div className="memory-doc">{m.document}</div>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function RecalledPanel({ state }) {
  const mem = state?.memories || {}
  return (
    <Panel title="Recalled">
      {(mem.recalled || []).length === 0 && <div style={{ color: '#555' }}>none yet</div>}
      {(mem.recalled || []).map((doc, i) => (
        <div key={i} style={{ padding: '3px 0', borderBottom: '1px solid #1a1a2a', color: '#aaa' }}>{doc}</div>
      ))}
      {(mem.recent_generated || []).length > 0 && (
        <>
          <div style={{ color: '#666', marginTop: 8, fontSize: 11, fontWeight: 700 }}>Recently Generated</div>
          {mem.recent_generated.map((doc, i) => (
            <div key={i} style={{ padding: '3px 0', borderBottom: '1px solid #1a1a2a', color: '#7c9cff' }}>{doc}</div>
          ))}
        </>
      )}
    </Panel>
  )
}

export default function App() {
  const [state, setState] = useState(null)
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)

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

  return (
    <div className="dashboard">
      <Header state={state} connected={connected} />
      <div className="left-col">
        <StatusPanel state={state} />
        <OnlinePanel state={state} />
        <PipelinePanel state={state} />
      </div>
      <div className="center-col">
        <ConversationPanel state={state} />
        <ZeitgeistPanel state={state} />
      </div>
      <div className="right-col">
        <MemoriesPanel state={state} />
        <RecalledPanel state={state} />
      </div>
    </div>
  )
}
