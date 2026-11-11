import {useCallback, useEffect, useRef, useState} from 'react'
import {createRoot} from 'react-dom/client'
import {ArrowLeft, ArrowRight, Check, ChevronRight, CircleHelp, ClipboardCheck, Clock3, FolderOpen, History, House, Layers3, Menu, Pause, Play, Plus, RotateCcw, SkipBack, SkipForward, Sparkles, TriangleAlert, X} from './icons'
import {errorText, post, projectPath, request} from './api'
import {PlanPanel} from './PlanCanvas'
import {Avatar, BudgetSummary, ChatCard, Collaboration, ProposalCard, StylePanel, ValidationDetails} from './Panels'
import {Workspace} from './Workspace'
import {eventTime, roles} from './types'
import type {Action, Artifact, Draft, Estimate, Health, Operation, Page, Plan, Project, Proposal, Role, RoomEvent, RunStatus, StyleBoard, Validation} from './types'
import './styles.css'

const PAGE_LABELS: Record<Page, string> = {overview: 'Overview', workspace: 'Workspace', approvals: 'Approvals', timeline: 'Activity'}
const NAVIGATION = [{page: 'overview', icon: House}, {page: 'workspace', icon: FolderOpen}, {page: 'approvals', icon: ClipboardCheck}, {page: 'timeline', icon: History}] as const
const PHASES: Record<string, string> = {
  requirements: 'Collecting requirements', reconciling: 'Reconciling briefs', designing: 'Generating layout',
  costing: 'Calculating estimate', negotiation: 'Decision needed', revising: 'Revising layout', review: 'Ready for review',
  approved: 'Approved', changes_requested: 'Changes requested', failed: 'Needs attention',
}

function ScanLineNotice({phase, confirmed}: {phase: string; confirmed: number}) {
  return <span>{phase === 'requirements'
    ? `Room outline loaded. A furniture layout is not generated yet. Confirm both client briefs to generate it (${confirmed}/2 confirmed).`
    : phase === 'failed' ? 'Layout generation needs attention. Open Approvals to retry the workflow.'
    : 'The agents are preparing and validating the furniture layout. The canvas will update when a valid draft is ready.'}</span>
}

function useHealth() {
  const [data, setData] = useState<Health | null>(null)
  const [error, setError] = useState('')
  const reload = useCallback(() => {
    setError('')
    request<Health>('/health').then(setData).catch(reason => setError(errorText(reason)))
  }, [])
  useEffect(reload, [reload])
  return {data, error, reload}
}

function Dialog({title, children, onClose, drawer = false}: {title: string; children: React.ReactNode; onClose: () => void; drawer?: boolean}) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    box.current?.focus()
    return () => previous?.focus()
  }, [])
  return <div className={drawer ? 'drawer-backdrop' : 'modal-backdrop'} onClick={event => {if (event.target === event.currentTarget) onClose()}}>
    <div ref={box} tabIndex={-1} className={drawer ? 'drawer' : 'modal'} role="dialog" aria-modal="true" aria-label={title} onKeyDown={event => {
      if (event.key === 'Escape') onClose()
      if (event.key !== 'Tab') return
      const targets = Array.from(box.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href]') || [])
      const first = targets[0], last = targets.at(-1)
      if (event.shiftKey && (document.activeElement === first || document.activeElement === box.current)) {event.preventDefault(); last?.focus()}
      if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus()}
    }}>
      <header className="drawer-header"><h2>{title}</h2><button className="icon-button" title="Close dialog" onClick={onClose}><X size={19}/></button></header>
      <div className="drawer-body">{children}</div>
    </div>
  </div>
}

function Dashboard({health}: {health: Health}) {
  const params = new URLSearchParams(window.location.search)
  const projectId = params.get('project') || health.default_project_id
  const base = projectPath(projectId)
  const [page, setPage] = useState<Page>('overview')
  const [mobile, setMobile] = useState(false)
  const [project, setProject] = useState<Project | null>(null)
  const [events, setEvents] = useState<RoomEvent[]>([])
  const [files, setFiles] = useState<Artifact[]>([])
  const [planArtifact, setPlanArtifact] = useState<Artifact<Plan> | null>(null)
  const [room, setRoom] = useState<(Plan['space'] & {fixed_features: Plan['fixed_features']}) | null>(null)
  const [report, setReport] = useState<Validation | null>(null)
  const [estimate, setEstimate] = useState<Estimate | null>(null)
  const [style, setStyle] = useState<StyleBoard | null>(null)
  const [chosenVersion, setChosenVersion] = useState<number | null>(null)
  const [artifactId, setArtifactId] = useState('plan')
  const [selected, setSelected] = useState<string[]>([])
  const [at, setAt] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [connected, setConnected] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [error, setError] = useState('')
  const [dialog, setDialog] = useState<'validation' | 'new' | 'help' | null>(null)
  const [candidate, setCandidate] = useState<{plan: Plan; validation: Validation} | null>(null)
  const [pending, setPending] = useState<Partial<Record<Role, string>>>({})
  const [projectName, setProjectName] = useState('')
  const [projectBudget, setProjectBudget] = useState('1500000')
  const [newBusy, setNewBusy] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [timelineFilter, setTimelineFilter] = useState('all')
  const [geometryError, setGeometryError] = useState('')
  const [geometryBusy, setGeometryBusy] = useState(false)
  const patchRequest = useRef<{signature: string; key: string} | null>(null)
  const visibleEvents = at === null ? events : events.filter(event => event.seq <= at)
  const liveSeq = events.at(-1)?.seq || 0
  const visibleSeq = visibleEvents.at(-1)?.seq || 0
  const query = at === null ? '' : `?at=${at}`
  const state = project?.state
  const selectedPlanEntry = files.find(file => file.id === 'plan')
  const versions = selectedPlanEntry?.versions || []
  const appliedVersion = visibleEvents.filter(event => event.type === 'canvas.patch.applied').at(-1)?.payload.plan_version || 0
  const latestVisibleVersion = at !== null && (versions[0] || 0) > 1 ? appliedVersion || 1 : versions[0] || 0
  const version = chosenVersion && versions.includes(chosenVersion) ? chosenVersion : latestVisibleVersion
  const plan = planArtifact?.version === version ? planArtifact.body : null
  const [livePatchCount, setLivePatchCount] = useState(0)
  const patchEvents = visibleEvents.filter(event => event.type === 'canvas.patch.applied' && event.payload.plan_version === version)
  const patchCount = at === null ? livePatchCount : patchEvents.length
  const partialPatch = version === 1 && patchCount < (patchEvents.at(-1)?.payload.batch_size || 4)
    ? patchEvents.slice(0, patchCount).flatMap(event => event.payload.operations || []) : null
  const changed = patchEvents.flatMap(event => (event.payload.operations || []).filter(operation => operation.op === 'update').map(operation => operation.object_id))
  const pendingProposal = [state?.review, state?.negotiation].find(proposal => proposal?.status === 'pending')
  const currentProject = project
  const update = () => setRefresh(value => value + 1)

  useEffect(() => {setLivePatchCount(0)}, [version])
  useEffect(() => {
    if (at !== null || version !== 1 || livePatchCount >= patchEvents.length) return
    const timer = window.setTimeout(() => setLivePatchCount(count => count + 1), 300)
    return () => window.clearTimeout(timer)
  }, [at, version, livePatchCount, patchEvents.length])

  useEffect(() => {
    const controller = new AbortController()
    let cursor = 0
    const poll = async () => {
      while (!controller.signal.aborted) {
        try {
          const batch = await request<{events: RoomEvent[]; next_seq: number}>(`${base}/events?after_seq=${cursor}&wait=15`, '', {signal: controller.signal})
          if (controller.signal.aborted) return
          setConnected(true)
          cursor = batch.next_seq
          if (batch.events.length) {
            setEvents(previous => {
              const tail = previous.at(-1)?.seq || 0
              return [...previous, ...batch.events.filter(event => event.seq > tail)]
            })
          }
        } catch (reason) {
          if (controller.signal.aborted) return
          setConnected(false)
          await new Promise(resolve => window.setTimeout(resolve, 1200))
        }
      }
    }
    void poll()
    return () => controller.abort()
  }, [base])

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      request<Project>(`${base}${query}`, '', {signal: controller.signal}),
      request<Artifact[]>(`${base}/workspace${query}`, '', {signal: controller.signal}),
    ]).then(([metadata, artifacts]) => {setProject(metadata); setFiles(artifacts)}).catch(reason => {
      if (!controller.signal.aborted) setError(errorText(reason))
    })
    return () => controller.abort()
  }, [base, query, visibleSeq, refresh])

  const currentEstimate = files.find(file => file.id === 'estimate')?.version || 0
  const currentStyle = files.find(file => file.id === 'style')?.version || 0
  const currentValidation = files.find(file => file.id === 'validation')?.version || 0
  const currentRoom = files.find(file => file.id === 'room')?.version || 0
  useEffect(() => {
    const controller = new AbortController()
    const load = <T,>(id: string, selectedVersion: number): Promise<T | null> => selectedVersion
      ? request<Artifact<T>>(`${base}/artifacts/${id}?version=${selectedVersion}`, '', {signal: controller.signal}).then(artifact => artifact.body)
      : Promise.resolve(null)
    Promise.all([
      version ? request<Artifact<Plan>>(`${base}/artifacts/plan?version=${version}`, '', {signal: controller.signal}) : Promise.resolve(null),
      load<Validation>('validation', Math.min(version, currentValidation)),
      load<Estimate>('estimate', currentEstimate),
      load<StyleBoard>('style', currentStyle),
      load<Plan['space'] & {fixed_features: Plan['fixed_features']}>('room', currentRoom),
    ]).then(([nextPlan, nextReport, nextEstimate, nextStyle, nextRoom]) => {
      if (controller.signal.aborted) return
      setPlanArtifact(nextPlan); setReport(nextReport); setEstimate(nextEstimate); setStyle(nextStyle); setRoom(nextRoom)
    }).catch(reason => {if (!controller.signal.aborted) setError(errorText(reason))})
    return () => controller.abort()
  }, [base, version, currentValidation, currentEstimate, currentStyle, currentRoom])

  useEffect(() => {
    if (!Object.keys(pending).length) return
    const controller = new AbortController()
    const timer = window.setInterval(() => {
      for (const [role, run] of Object.entries(pending)) {
        request<RunStatus>(`${base}/runs/${run}`, '', {signal: controller.signal}).then(result => {
          if (['completed', 'failed', 'cancelled'].includes(result.status)) setPending(previous => {
            if (previous[role as Role] !== run) return previous
            const next = {...previous}; delete next[role as Role]; return next
          })
        }).catch(() => undefined)
      }
    }, 650)
    return () => {window.clearInterval(timer); controller.abort()}
  }, [base, pending])

  const replayable = events.filter(event => event.visibility === 'shared' && event.type !== 'room.state')
  useEffect(() => {
    if (!playing || at === null) return
    const next = events.find(event => event.seq > at)
    if (!next) {setPlaying(false); return}
    const delay = next.type === 'room.state' ? 120 : next.type === 'canvas.patch.applied' ? 490 : 380
    const timer = window.setTimeout(() => setAt(next.seq), delay)
    return () => window.clearTimeout(timer)
  }, [at, events, playing])

  const goto = (target: Page) => {
    setPage(target); setMobile(false)
    window.scrollTo({top: 0, behavior: 'instant'})
  }
  const showArtifact = (id: string) => {setArtifactId(id); goto('workspace')}
  const exitReplay = () => {setAt(null); setPlaying(false); setChosenVersion(null)}
  const startReplay = () => {
    if (!replayable.length) return
    const firstHandoff = events.find(event => event.type === 'requirement.approved')
    setChosenVersion(null); setSelected([]); setAt(firstHandoff ? firstHandoff.seq - 1 : 0); setPlaying(true); goto('overview')
  }
  const stepReplay = (direction: number) => {
    setPlaying(false)
    const steps = [0, ...events.map(event => event.seq)]
    const index = steps.findIndex(step => step >= (at ?? liveSeq))
    setAt(steps[Math.max(0, Math.min(steps.length - 1, index + direction))])
  }
  const send = async (role: Role, content: string) => {
    const request_id = crypto.randomUUID()
    const result = await post<{run_id: string}>(`${base}/agents/${role}/messages`, {content, request_id}, '')
    setPending(previous => ({...previous, [role]: result.run_id}))
  }
  const decideBrief = async (role: Role, draft: Draft, action: 'approve' | 'request_changes') => {
    await post(`${base}/briefs/${role}/decision`, {expected_seq: draft.seq, action}, '')
    update()
  }
  const decide = async (proposal: Proposal, role: Role, action: Action) => {
    await post(`${base}/proposals/${proposal.id}/decision`, {expected_version: proposal.version, role, action}, '')
    update()
  }
  const alternate = async () => {
    try {await post(`${base}/runs`, {}, ''); update()}
    catch (reason) {setError(errorText(reason))}
  }
  const cancelRun = async (runId: string) => {
    setCancelling(true)
    try {await post(`${base}/runs/${runId}/cancel`, {}, ''); update()}
    catch (reason) {setError(errorText(reason))}
    finally {setCancelling(false)}
  }
  const editPlacement = async (id: string, changes: {center_mm: [number, number]; rotation_deg: number}, reason: string) => {
    if (!plan || !planArtifact || at !== null || version !== state?.plan_version) throw new Error('Wait for the latest floor plan to load before editing.')
    const body = {base_version: planArtifact.version, expected_state_hash: `sha256:${planArtifact.sha}`,
      operations: [{op: 'update', object_id: id, changes}], reason}
    const signature = JSON.stringify(body)
    if (patchRequest.current?.signature !== signature) patchRequest.current = {signature, key: crypto.randomUUID()}
    await post(`${base}/plans/${plan.plan_id}/patches`, {...body, idempotency_key: patchRequest.current.key}, '')
    setChosenVersion(null); setSelected([]); update()
  }
  const inspectCandidate = async (event: RoomEvent) => {
    setDialog('validation'); setCandidate(null); setGeometryError(''); setGeometryBusy(true)
    try {
      type Candidates = Artifact<{plan: Plan; validation: Validation}[]>
      const history = at === null ? '' : `&at=${at}`
      const file = await request<Candidates>(`${base}/artifacts/candidate${query}`)
      let entries = file.body
      for (const candidateVersion of file.versions) {
        if (entries.some(entry => entry.plan.plan_version === event.payload.plan_version)) break
        if (candidateVersion !== file.version) entries = (await request<Candidates>(`${base}/artifacts/candidate?version=${candidateVersion}${history}`)).body
      }
      const failed = entries.find(entry => entry.plan.plan_version === event.payload.plan_version && entry.validation.status === 'failed' &&
        entry.validation.checks.some(check => event.payload.checks?.some(other => other.message === check.message)))
      if (!failed) throw new Error('This candidate is available in its recorded layout artifact.')
      setCandidate(failed)
    } catch (reason) {setGeometryError(errorText(reason))}
    finally {setGeometryBusy(false)}
  }
  const newProject = async (event: React.FormEvent) => {
    event.preventDefault()
    setNewBusy(true); setError('')
    try {
      const created = await post<{id: string}>('/projects', {name: projectName, budget: Number(projectBudget)}, '')
      window.location.assign(`?project=${created.id}`)
    } catch (reason) {setError(errorText(reason)); setNewBusy(false)}
  }

  if (!currentProject || !state) return <div className="app-loading"><Layers3 size={34}/><h1>AgentRoom Interior</h1>
    <p>{error || 'Opening the design workspace…'}</p>{error && <button className="button secondary" onClick={update}>Try again</button>}</div>

  const timeline = visibleEvents.filter(event => event.type !== 'room.state' && (timelineFilter === 'all' ||
    (timelineFilter === 'files' && event.type.startsWith('workspace.')) || (timelineFilter === 'decisions' && event.type.startsWith('approval.')) ||
    (timelineFilter === 'agents' && event.type.startsWith('agent.')))).slice().reverse()
  const hasApproval = pendingProposal?.required.some(role => !pendingProposal.decisions[role])
  const candidateReport = candidate?.validation || report
  const roomPreview: Plan | null = room ? {plan_id: 'kitchen-dining', plan_version: 0, space: room,
    fixed_features: room.fixed_features, objects: []} : null
  return <div className="app-shell">
    {mobile && <button className="mobile-nav-scrim" aria-label="Close navigation" onClick={() => setMobile(false)}/>}
    <aside className={`sidebar ${mobile ? 'mobile-nav-open' : ''}`}>
      <button className="sidebar-brand" onClick={() => goto('overview')}><span className="brand-icon"><Layers3 size={23}/></span><span className="brand-copy"><strong>AgentRoom</strong><small>INTERIOR</small></span></button>
      <div className="sidebar-project"><span className="sidebar-label">PROJECT</span><button className="project-key" onClick={() => goto('overview')}><span className="workspace-logo"><House size={17}/></span><span>{currentProject.name}<small>Kitchen & dining</small></span><ChevronRight size={13}/></button></div>
      <nav className="sidebar-nav" aria-label="Workspace navigation"><span className="sidebar-label">WORKSPACE</span>
        {NAVIGATION.map(({page: key, icon: Icon}) => <button className={`nav-item ${page === key ? 'active' : ''}`} aria-current={page === key ? 'page' : undefined} key={key} onClick={() => goto(key)}>
          <Icon size={18}/><span>{PAGE_LABELS[key]}</span>{key === 'approvals' && hasApproval && pendingProposal && <span className="nav-counter">{pendingProposal.required.filter(role => !pendingProposal.decisions[role]).length}</span>}
        </button>)}
      </nav>
      <div className="sidebar-bottom"><button className="nav-item" onClick={() => setDialog('help')}><CircleHelp size={17}/><span>Workspace guide</span></button>
        <button className="nav-item" onClick={() => setDialog('new')}><Plus size={18}/><span>New project</span></button>
        <div className="sidebar-bottom-note"><span className={`live-indicator ${connected ? '' : 'offline'}`}/>{health.mode === 'demo' ? 'Offline demo mode' : 'GMI Cloud live mode'}</div>
      </div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumbs">
        <button className="icon-button topbar-menu" title="Open navigation" onClick={() => setMobile(!mobile)}><Menu size={20}/></button>
        <span>Projects</span><ChevronRight size={13}/><strong>{currentProject.name}</strong>{page !== 'overview' && <><ChevronRight size={13}/><span>{PAGE_LABELS[page]}</span></>}
      </div><div className="topbar-actions">
        <div className="avatar-stack" aria-label="Four participants">{roles.map(role => <Avatar role={role} key={role} small/>)}</div>
        <span className="header-chip"><span className={`live-indicator ${connected ? '' : 'offline'}`}/>{connected ? 'Connected' : 'Reconnecting'}</span>
      </div></header>
      <main className="page-content">
        {health.mode === 'live' && !health.gmi_configured && <div className="overview-banner"><TriangleAlert size={17}/> Set <code>GMI_API_KEY</code> in the server environment and restart the API to enable live agents.</div>}
        {error && <div className="toast" role="alert"><TriangleAlert size={17}/><span>{error}</span><button className="icon-button" title="Dismiss error" onClick={() => setError('')}><X size={16}/></button></div>}
        {at === null && currentProject.active_runs.map(run => <div className="overview-banner" key={run.id}>
          <Clock3 size={17}/><span>Design workflow · {run.status} · {run.stage}</span>
          {['overview', 'design'].includes(currentProject.actor) && <button className="button small secondary" disabled={cancelling} onClick={() => void cancelRun(run.id)}>{cancelling ? 'Cancelling…' : 'Cancel run'}</button>}
        </div>)}
        {at !== null && <div className="replay-controls">
          <span><History size={16}/> Replay · event {at} / {liveSeq}</span>
          <div><button className="icon-button" title="Previous event" onClick={() => stepReplay(-1)} disabled={at === 0}><SkipBack size={15}/></button>
          <button className="icon-button" title={playing ? 'Pause replay' : 'Play replay'} onClick={() => setPlaying(!playing)} disabled={!playing && at === liveSeq}>{playing ? <Pause size={15}/> : <Play size={15}/>}</button>
          <button className="icon-button" title="Next event" onClick={() => stepReplay(1)} disabled={at === liveSeq}><SkipForward size={15}/></button></div>
          <input type="range" aria-label="Replay event" min={0} max={liveSeq} value={at} onChange={event => {setPlaying(false); setAt(Number(event.target.value))}}/>
          <button className="button small secondary" onClick={exitReplay}>Return to live</button>
        </div>}
        {page === 'overview' && <>
          <section className="project-hero">
            <div className="hero-copy"><div className="hero-meta"><span className="heading-kicker">RESIDENTIAL INTERIOR</span><span className={`badge ${state.phase === 'approved' ? 'good' : hasApproval ? 'warn' : 'quiet'}`}><i/>{PHASES[state.phase] || state.phase}</span></div>
              <h1>{currentProject.name}</h1><p className="project-location">Kitchen & dining renovation</p>
            </div>
            <div className="hero-actions"><button className="button secondary" onClick={startReplay} disabled={!replayable.length}><Play size={15}/> Replay {health.mode === 'demo' ? 'demo' : 'activity'}</button>
              <button className="button primary" onClick={() => goto(hasApproval ? 'approvals' : 'workspace')}>{hasApproval ? 'Review decision' : 'Open workspace'}<ArrowRight size={16}/></button>
            </div>
          </section>
           <div className="budget-strip"><BudgetSummary estimate={estimate} budget={currentProject.budget}
             stale={state.budget_stale || !!(estimate && version && estimate.source_plan_version !== version)}/></div>
          <div className="dashboard-grid">
            <PlanPanel plan={version ? plan : roomPreview} referenceOnly={!version} versions={versions} version={version} setVersion={value => {setChosenVersion(value); setSelected([])}} operations={partialPatch}
              selected={selected} setSelected={setSelected} approved={state.approved_plan_version === version} validation={!!report}
              onValidation={() => {setCandidate(null); setGeometryError(''); setDialog('validation')}} changed={version > 1 ? changed : []}
              onEdit={at === null && version === state.plan_version && !state.budget_stale && ['review', 'changes_requested'].includes(state.phase)
                && ['overview', 'design'].includes(currentProject.actor) ? editPlacement : undefined}/>
            <Collaboration events={visibleEvents} replaying={at !== null} onArtifact={showArtifact} onTimeline={() => goto('timeline')} onGeometry={event => void inspectCandidate(event)}/>
          </div>
          {!state.plan_version && at === null && <section className="overview-banner" role="status"><ScanLineNotice phase={state.phase} confirmed={state.confirmed_clients.length}/>
            <button className="button small secondary" onClick={() => document.getElementById('participant-conversations')?.scrollIntoView({behavior: 'smooth'})}>Open requirement chats</button></section>}
          <section className="chat-section" id="participant-conversations">
            <div className="section-heading"><div className="section-copy"><h2>Participant conversations</h2><p>Each participant has a separate thread with their assigned agent.</p></div><span className="badge quiet">Local overview</span></div>
            <div className="chat-grid">{roles.map(role => <ChatCard key={role} role={role} project={currentProject} events={visibleEvents}
              editable={at === null} pending={!!pending[role]} onSend={content => send(role, content)} onDecide={(draft, action) => decideBrief(role, draft, action)}/>)}</div>
          </section>
          <div className="lower-grid"><StylePanel style={style}/>
            {pendingProposal && <div className="panel quick-review"><div className="quick-review-copy"><span className="panel-icon"><ClipboardCheck size={18}/></span><div><h2>{pendingProposal.label}</h2><p>{pendingProposal.summary}</p></div></div><button className="button secondary" onClick={() => goto('approvals')}>Open approvals <ArrowRight size={15}/></button></div>}
          </div>
        </>}
        {page !== 'overview' && <div className="page-heading"><button className="text-button" onClick={() => goto('overview')}><ArrowLeft size={15}/> Project overview</button><h1>{PAGE_LABELS[page]}</h1>
          <p>{page === 'workspace' ? 'Inspect files, version changes, and source dependencies.' : page === 'approvals' ? 'Review decisions for the current plan and estimate.' : 'Trace decisions, model activity, and file changes by event.'}</p></div>}
        {page === 'workspace' && <Workspace projectId={projectId} token="" at={at} files={files}
          active={files.some(file => file.id === artifactId) ? artifactId : files[0]?.id || ''} setActive={setArtifactId} events={visibleEvents}/>}
        {page === 'approvals' && <div className="approvals-grid">
          {[state.review, state.negotiation].filter((item): item is Proposal => !!item).map(proposal =>
            <ProposalCard key={proposal.id} proposal={proposal} project={currentProject} readOnly={at !== null} onDecision={decide}/>)}
          {!state.review && !state.negotiation && <div className="panel empty"><ClipboardCheck size={24}/><strong>No shared decisions yet</strong><p>Confirm the client briefs to begin the design workflow.</p></div>}
          {at === null && ['failed', 'changes_requested'].includes(state.phase) && <div className="panel quick-review"><div className="quick-review-copy"><span className="panel-icon"><RotateCcw size={17}/></span><div><h2>Review another option</h2><p>Resume a failed run or ask the design agent for a new proposal.</p></div></div><button className="button primary" onClick={() => void alternate()}>Request alternative <ArrowRight size={15}/></button></div>}
        </div>}
        {page === 'timeline' && <section className="panel timeline-panel">
          <header className="panel-header"><div className="panel-heading"><span className="panel-icon"><History size={17}/></span><div><h2>Recorded events</h2><p>Event sequence and provenance</p></div></div>
            <select className="simple-select" aria-label="Filter event timeline" value={timelineFilter} onChange={event => setTimelineFilter(event.target.value)}><option value="all">All events</option><option value="files">Files</option><option value="agents">Agents</option><option value="decisions">Decisions</option></select></header>
          {timeline.map(event => <article className="timeline-row" key={event.event_id}>
            <span className="timeline-seq">#{event.seq}</span><span className="event-icon plain"><Clock3 size={15}/></span>
            <div><strong>{event.actor}</strong><span className="event-type">{event.type.replaceAll('.', ' ').replaceAll('_', ' ')}</span>
              <p>{event.visibility !== 'shared' ? 'Private activity' : event.payload.summary || event.payload.content || 'Recorded workflow event'}</p></div>
            <time>{eventTime(event.timestamp)}</time><button className="icon-button" title={`Replay event ${event.seq}`} onClick={() => {setAt(event.seq); setPlaying(false); setChosenVersion(null); goto('overview')}}><Play size={15}/></button>
          </article>)}
          {!timeline.length && <div className="empty"><History size={24}/><strong>No matching events</strong></div>}
        </section>}
      </main>
    </div>
    {dialog === 'validation' && <Dialog title="Spatial validation" drawer onClose={() => setDialog(null)}>
      {geometryBusy ? <p>Loading candidate…</p> : geometryError ? <p className="inline-error">{geometryError}</p> :
        candidateReport && <ValidationDetails report={candidateReport} onPick={ids => {
          if (candidate) return
          setSelected(ids); setDialog(null)
        }}/>}
      {candidate && <div className="candidate-details"><h3>Candidate placements</h3>{candidate.plan.objects.map(object => <p key={object.id}>{object.label} · {object.center_mm.join(', ')} mm</p>)}</div>}
    </Dialog>}
    {dialog === 'new' && <Dialog title="New project" onClose={() => setDialog(null)}>
      <form className="project-form" onSubmit={event => void newProject(event)}>
        <label>Project name<input value={projectName} minLength={2} maxLength={72} required onChange={event => setProjectName(event.target.value)} placeholder="e.g. The Cedar Residence"/></label>
        <label>Budget (TWD)<input type="number" min={1} max={100000000} value={projectBudget} required onChange={event => setProjectBudget(event.target.value)}/></label>
        {error && <p className="inline-error">{error}</p>}<button className="button primary" disabled={newBusy}>{newBusy ? 'Creating…' : 'Create project'}<ArrowRight size={16}/></button>
      </form>
    </Dialog>}
    {dialog === 'help' && <Dialog title="Workspace guide" onClose={() => setDialog(null)}>
      <div className="guide"><p><Sparkles size={17}/> {health.mode === 'demo' ? 'Demo mode uses local scenario logic and simulated prices.' : `All three agents use ${health.model} through GMI Cloud.`}</p>
        <p><Check size={17}/> Confirm one brief from each client, then review the island trade-off and the design package.</p>
        <p><Layers3 size={17}/> This local overview gives the operator access to all four participant threads.</p>
        <p><History size={17}/> Replay uses the persisted event log. Sending messages and approving changes are disabled during playback.</p></div>
    </Dialog>}
  </div>
}

function App() {
  const {data, error, reload} = useHealth()
  if (data) return <Dashboard health={data}/>
  return <div className="app-loading"><Layers3 size={36}/><h1>AgentRoom Interior</h1><p>{error ? 'The local API could not be reached.' : 'Opening the design workspace…'}</p>
    {error && <button className="button secondary" onClick={reload}><RotateCcw size={16}/> Try again</button>}</div>
}

createRoot(document.getElementById('root')!).render(<App/>)
