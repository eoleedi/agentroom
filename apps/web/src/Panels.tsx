import {useEffect, useRef, useState} from 'react'
import {ArrowDownRight, ArrowRight, ArrowUpRight, Bot, Check, CheckCircle2, ChevronRight, Clock3, FileText, GitBranch, History, Hourglass, LockKeyhole, MessageSquare, Send, ShieldCheck, Sparkles, TriangleAlert, Wrench} from './icons'
import {errorText} from './api'
import {eventTime, money, roleLabels} from './types'
import type {Action, Draft, Estimate, Project, Proposal, Role, RoomEvent, StyleBoard, Validation} from './types'

export function Avatar({role, small = false}: {role: Role; small?: boolean}) {
  const info = roleLabels[role]
  return <span className={`avatar ${info.tone} ${small ? 'avatar-small' : ''}`}>{info.initials}</span>
}

export function BudgetSummary({estimate, budget, stale}: {estimate: Estimate | null; budget: number; stale: boolean}) {
  return <div className="budget-summary">
    <div><span>PROJECT BUDGET</span><strong>{money(budget)}</strong></div>
    <div><span>{stale ? 'ESTIMATE OUTDATED' : 'CURRENT ESTIMATE'}</span><strong>{estimate ? money(estimate.estimated_total) : '—'}</strong></div>
    <div className="budget-status">
      {stale ? <span className="badge warn"><Clock3 size={13}/> Recalculating</span> : estimate && <span className={`badge ${estimate.remaining < 0 ? 'warn' : 'good'}`}>
        {estimate.remaining < 0 ? <ArrowUpRight size={14}/> : <ArrowDownRight size={14}/>}
        {money(estimate.remaining)} {estimate.remaining < 0 ? 'over' : 'remaining'}
      </span>}
    </div>
  </div>
}

export function Collaboration({events, onArtifact, onTimeline, onGeometry}: {
  events: RoomEvent[]; onArtifact: (id: string) => void; onTimeline: () => void; onGeometry: (event: RoomEvent) => void
}) {
  const [filter, setFilter] = useState<'all' | 'messages' | 'tools'>('all')
  const relevant = events.filter(event => event.visibility === 'shared' &&
    (event.type === 'agent.message' || event.type === 'agent.tool_event' || event.type.startsWith('agent.task.') || event.type.startsWith('workspace.file.')))
  const listed = relevant.filter(event => filter === 'all' || (filter === 'messages' ? event.type === 'agent.message' : event.type !== 'agent.message'))
  const scroll = useRef<HTMLDivElement>(null)
  const seen = useRef(0)
  useEffect(() => {
    if (seen.current && relevant.length > seen.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight
    seen.current = relevant.length
  }, [relevant.length])
  return <section className="panel feed-panel">
    <header className="panel-header"><div className="panel-heading"><span className="panel-icon"><GitBranch size={17}/></span><div><h2>Agent room</h2><p>Shared collaboration</p></div></div>
      <span className="badge good feed-status"><i/> Live feed</span></header>
    <div className="tabs feed-tabs" aria-label="Filter collaboration">
      {(['all', 'messages', 'tools'] as const).map(key => <button key={key} className={filter === key ? 'active' : ''}
        onClick={() => {setFilter(key); if (scroll.current) scroll.current.scrollTop = 0}}>{key === 'all' ? 'All activity' : key === 'messages' ? 'Messages' : 'Tools'}</button>)}
    </div>
    <div className="feed-list" ref={scroll}>
      {!listed.length && <div className="empty"><MessageSquare size={23}/><strong>No activity yet</strong><p>Agent handoffs and tool checks appear here.</p></div>}
      {listed.map(event => {
        const message = event.type === 'agent.message'
        const failed = event.payload.status === 'failed' || event.type.endsWith('.failed')
        const tone = event.actor.startsWith('Requirement') ? 'rose' : event.actor.startsWith('Budget') ? 'sage' : 'lavender'
        return <article className="feed-event" key={event.event_id}>
          <span className={`event-icon ${message ? tone : failed ? 'peach' : 'plain'}`}>{message ? <Bot size={16}/> : failed ? <TriangleAlert size={15}/> : <Wrench size={15}/>}</span>
          <div className="event-copy">
            <div className="event-heading"><strong>{message ? event.actor.replace(' Agent', '') : event.type.startsWith('workspace.file.') ? `${event.type.endsWith('read') ? 'READ' : 'WRITE'} · ${event.actor.replace(' Agent', '')}` : event.type.startsWith('agent.task.') ? `${event.actor.replace(' Agent', '')} · ${event.type.split('.').at(-1)}` : event.payload.tool === 'validate_geometry' ? 'Geometry check' : event.payload.tool === 'calculate_estimate' ? 'Cost calculation' : 'Agent tool'}</strong>
              {message && <><ArrowRight size={12}/><span>{event.payload.recipient?.replace(' Agent', '')}</span></>}
              <time>{eventTime(event.timestamp)}</time>
            </div>
            <p>{event.payload.content || event.payload.summary}</p>
            <small className="event-provenance">#{event.seq} · Run {event.run_id.slice(0, 8)} · {message ? 'Shared message' : event.type.startsWith('workspace.') ? 'File activity' : 'Tool / task event'}</small>
            {event.payload.artifact_id && <button className="artifact-link" onClick={() => onArtifact(event.payload.artifact_id!)}><FileText size={12}/>{({brief: 'Design brief', bom: 'Material BOM', estimate: 'Estimate', conflict: 'Change request'} as Record<string,string>)[event.payload.artifact_id] || event.payload.artifact_id}<ChevronRight size={11}/></button>}
            {event.payload.checks && event.payload.checks.length > 0 && <button className="artifact-link" onClick={() => onGeometry(event)}><TriangleAlert size={12}/> Inspect candidate <ChevronRight size={11}/></button>}
          </div>
        </article>
      })}
    </div>
    <button className="feed-footer" onClick={onTimeline}><History size={15}/> View activity timeline <ArrowRight size={14}/></button>
  </section>
}

export function ChatCard({role, project, events, editable, pending, onSend, onDecide}: {
  role: Role; project: Project; events: RoomEvent[]; editable: boolean; pending: boolean;
  onSend: (content: string) => Promise<void>; onDecide: (draft: Draft, action: 'approve' | 'request_changes') => Promise<void>
}) {
  const info = roleLabels[role]
  const [input, setInput] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const thread = useRef<HTMLDivElement>(null)
  const messages = events.filter(event => event.type === 'private.message.created' && event.payload.role === role)
  const lastError = events.slice().reverse().find(event => event.payload.role === role && event.type === 'agent.task.failed')
  const showError = lastError && lastError.seq > (messages.at(-1)?.seq || 0)
  const draft = project.drafts[role]
  const suggestion = project.suggested_messages[role]
  useEffect(() => {if (thread.current) thread.current.scrollTop = thread.current.scrollHeight}, [messages.length, showError])
  const handle = async (work: () => Promise<void>) => {
    setBusy(true); setError('')
    try {await work()} catch (reason) {setError(errorText(reason))} finally {setBusy(false)}
  }
  return <article className="panel chat-card">
    <header className="chat-header"><Avatar role={role}/><div><h3>{project.participants[role]}</h3><p>{info.role}</p></div><LockKeyhole size={14} className="lock" aria-label="Private conversation"/></header>
    <div className="agent-label"><Sparkles size={13}/> {info.agent}{project.state.confirmed_clients.includes(role) && <Check size={14} className="success"/>}</div>
    <div ref={thread} className="thread" aria-live="polite">
      {messages.length ? messages.map(event => <p key={event.event_id} className={`bubble ${event.payload.speaker || 'agent'}`}>{event.payload.content}</p>) :
        <p className="chat-empty">{role === 'budget' ? 'Ask about an estimate or a material trade-off.' : role === 'design' ? 'Ask about dimensions, furniture, or validation.' : 'Share your preferences with the Requirement Agent.'}</p>}
      {pending && <p className="bubble agent thinking">Agent is responding…</p>}
      {showError && <p className="inline-error">{lastError.payload.summary}</p>}
    </div>
    {draft && <div className="brief-card">
      <strong>Confirm your brief</strong><p>{draft.brief.style} · {draft.brief.seating} seats · {draft.brief.island} island</p>
      <p>Priority: {draft.brief.priority.replaceAll('_', ' ')} · Storage: {draft.brief.storage.replaceAll('_', ' ')}</p>
      <div className="button-row">
        <button className="button small secondary" disabled={!editable || busy} onClick={() => void handle(() => onDecide(draft, 'request_changes'))}>Revise</button>
        <button className="button small primary" disabled={!editable || busy} onClick={() => void handle(() => onDecide(draft, 'approve'))}>Confirm</button>
      </div>
    </div>}
    {error && <p className="inline-error">{error}</p>}
    {!messages.length && suggestion && editable && <button className="text-button suggestion" onClick={() => setInput(suggestion)}>Use demo message <ChevronRight size={13}/></button>}
    <form className="chat-form" onSubmit={event => {
      event.preventDefault()
      if (!input.trim()) return
      const content = input
      void handle(async () => {await onSend(content); setInput('')})
    }}>
      <input aria-label={`Message ${info.agent} as ${project.participants[role]}`} maxLength={2000} placeholder="Write a message…" value={input}
        onChange={event => setInput(event.target.value)} disabled={!editable || busy || pending}/>
      <button type="submit" title="Send message" disabled={!editable || !input.trim() || busy || pending}><Send size={15}/></button>
    </form>
  </article>
}

export function StylePanel({style}: {style: StyleBoard | null}) {
  if (!style) return null
  return <section className="panel style-panel">
    <header className="panel-header"><div className="panel-heading"><span className="panel-icon"><Sparkles size={17}/></span><div><h2>Material palette</h2><p>{style.direction}</p></div></div></header>
    <div className="material-grid">{Object.entries(style.materials).map(([id, material]) =>
      <div key={id} className="material"><div className={`swatch swatch-${id}`} style={{backgroundColor: material.hex}}/><span>{material.label}</span></div>)}</div>
  </section>
}

export function ProposalCard({proposal, project, readOnly, onDecision}: {
  proposal: Proposal; project: Project; readOnly: boolean; onDecision: (proposal: Proposal, role: Role, action: Action) => Promise<void>
}) {
  const [busy, setBusy] = useState<Role | null>(null)
  const [error, setError] = useState('')
  const act = async (role: Role, action: Action) => {
    setBusy(role); setError('')
    try {await onDecision(proposal, role, action)} catch (reason) {setError(errorText(reason))} finally {setBusy(null)}
  }
  return <section className="panel proposal-card">
    <header className="panel-header"><div className="panel-heading"><span className="panel-icon"><ShieldCheck size={17}/></span><div><h2>{proposal.label}</h2><p>Plan version {proposal.plan_version}</p></div></div>
      <span className={`badge ${proposal.status === 'approved' ? 'good' : 'warn'}`}>{proposal.status === 'pending' ? 'Needs approval' : proposal.status.replaceAll('_', ' ')}</span>
    </header>
    <div className="proposal-content"><p>{proposal.summary}</p>
      {proposal.savings !== undefined && <div className="tradeoff-values"><div><span>PROJECTED ESTIMATE</span><strong>{money(proposal.projected_total!)}</strong></div><div><span>PROJECTED SAVINGS</span><strong className="success">{money(proposal.savings)}</strong></div></div>}
      {error && <p className="inline-error">{error}</p>}
      {proposal.required.map(role => {
        const decision = proposal.decisions[role]
        const canDecide = !readOnly && (project.actor === role || project.actor === 'overview') && proposal.status === 'pending' && !decision
        return <div className="approval-row" key={role}><Avatar role={role} small/><div className="approval-person"><strong>{project.participants[role]}</strong><p>{roleLabels[role].role}</p></div>
          {canDecide ? <div className="approval-actions"><button className="button small secondary" disabled={busy !== null} onClick={() => void act(role, 'reject')}>Decline</button><button className="button small secondary" disabled={busy !== null} onClick={() => void act(role, 'request_changes')}>Request changes</button>
            <button className="button small primary" disabled={busy !== null} onClick={() => void act(role, 'approve')}><Check size={14}/> Approve</button></div>
            : <span className={`badge ${decision?.action === 'approve' ? 'good' : 'quiet'}`}>{decision?.action === 'approve' ? <><Check size={13}/> Approved</> : decision ? decision.action.replaceAll('_', ' ') : <><Hourglass size={12}/> Pending</>}</span>}
        </div>
      })}
    </div>
  </section>
}

export function ValidationDetails({report, onPick}: {report: Validation; onPick: (ids: string[]) => void}) {
  return <div className="validation-details">
    <p className={report.status === 'passed' ? 'success' : 'inline-error'}>
      {report.status === 'passed' ? <CheckCircle2 size={17}/> : <TriangleAlert size={17}/>}
      {report.status === 'passed' ? 'All modeled checks passed.' : report.status === 'failed' ? 'This layout has spatial conflicts.' : 'Verified dimensions are needed.'}
    </p>
    {report.checks.map((item, index) => <button className="validation-item" key={index} onClick={() => onPick(item.object_ids)}><TriangleAlert size={16}/><span>{item.message}</span><ChevronRight size={14}/></button>)}
    {report.clearances.map(item => <button className="validation-item" key={item.object_ids.join('-')} onClick={() => onPick(item.object_ids)}>
      <span>{item.object_ids.includes('table_01') ? 'Island to dining table' : 'Kitchen run to island'}</span><strong>{item.measured_mm.toLocaleString()} mm</strong><ChevronRight size={14}/>
    </button>)}
    <p className="validation-source">Required aisle clearance: 900 mm under the demo ruleset. Site measurements and building-code compliance are unverified.</p>
  </div>
}
