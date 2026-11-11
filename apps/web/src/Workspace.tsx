import {useEffect, useState} from 'react'
import {ArrowDownToLine, ArrowLeft, Check, ChevronRight, FileCode2, FileImage, FileText, FolderClosed, FolderOpen, GitCompareArrows, History} from './icons'
import {errorText, projectPath, request} from './api'
import type {Artifact, RoomEvent} from './types'
import {eventTime} from './types'

export function Workspace({projectId, token, at, files, active, setActive, events}: {
  projectId: string; token: string; at: number | null; files: Artifact[]; active: string;
  setActive: (id: string) => void; events: RoomEvent[]
}) {
  const [version, setVersion] = useState(0)
  const [preview, setPreview] = useState<Artifact | null>(null)
  const [compare, setCompare] = useState(false)
  const [diff, setDiff] = useState<string[]>([])
  const [error, setError] = useState('')
  const [closed, setClosed] = useState<string[]>([])
  const [dependency, setDependency] = useState<{artifact_id: string; version: number} | null>(null)
  const file = files.find(entry => entry.id === active)
  const current = dependency?.artifact_id === active && file?.versions.includes(dependency.version) ? dependency.version
    : version && file?.versions.includes(version) ? version : file?.version
  const groups = files.reduce<Record<string, Artifact[]>>((result, entry) => {
      const directory = entry.path.split('/')[0]
      return {...result, [directory]: [...(result[directory] || []), entry]}
    }, {})
  useEffect(() => {
    setVersion(0); setCompare(false)
  }, [active])
  useEffect(() => {
    if (!file || !current) return
    const controller = new AbortController()
    const base = `${projectPath(projectId)}/artifacts/${file.id}`
    const history = at === null ? '' : `&at=${at}`
    setError('')
    request<Artifact>(`${base}?version=${current}${history}`, token, {signal: controller.signal})
      .then(setPreview).catch(reason => {if (!controller.signal.aborted) setError(errorText(reason))})
    if (compare && current > 1) {
      request<{lines: string[]}>(`${base}/diff?from=${current-1}&to=${current}`, token, {signal: controller.signal})
        .then(data => setDiff(data.lines)).catch(reason => {if (!controller.signal.aborted) setError(errorText(reason))})
    }
    return () => controller.abort()
  }, [projectId, token, at, file?.id, current, compare])
  const shown = preview?.id === file?.id && preview?.version === current ? preview : null
  const activity = events.filter(event => event.type.startsWith('workspace.file.') && event.payload.artifact_id === active).slice(-8).reverse()
  const download = () => {
    if (!shown) return
    const content = typeof shown.body === 'string' ? shown.body : JSON.stringify(shown.body, null, 2)
    const url = URL.createObjectURL(new Blob([content], {type: shown.path.endsWith('.svg') ? 'image/svg+xml' : 'text/plain'}))
    const link = document.createElement('a')
    link.href = url; link.download = shown.path.split('/').at(-1) || 'artifact'
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <div className="workspace-grid">
    <section className="panel files-panel">
      <header className="panel-header"><div className="panel-heading"><span className="panel-icon"><FolderOpen size={17}/></span><div><h2>Project files</h2><p>{files.length} artifacts</p></div></div></header>
      <div className="file-tree">
        {Object.entries(groups).map(([directory, entries]) => <div key={directory} className="file-group">
          <button className="folder-row" aria-expanded={!closed.includes(directory)} onClick={() => setClosed(closed.includes(directory) ? closed.filter(name => name !== directory) : [...closed, directory])}>
            <ChevronRight size={13} className={closed.includes(directory) ? '' : 'folder-open'}/>{closed.includes(directory) ? <FolderClosed size={16}/> : <FolderOpen size={16}/>}
            {directory}
          </button>
          {!closed.includes(directory) && (entries || []).map(entry => <button key={entry.id} onClick={() => {setDependency(null); setActive(entry.id)}} className={`file-row ${active === entry.id ? 'active' : ''}`}>
            {entry.path.endsWith('.svg') ? <FileImage size={15}/> : entry.path.endsWith('.md') ? <FileText size={15}/> : <FileCode2 size={15}/>}
            <span>{entry.path.split('/').at(-1)}</span><small>v{entry.version}</small>
          </button>)}
        </div>)}
      </div>
    </section>
    <div className="workspace-detail">
      <section className="panel preview-panel">
        <header className="panel-header">
          <div className="panel-heading"><span className="panel-icon"><FileCode2 size={17}/></span><div><h2>{file?.path.split('/').at(-1) || 'Artifact preview'}</h2><p>{file ? `${file.owner} · ${file.status.replaceAll('_', ' ')}` : 'Select a project file'}</p></div></div>
          {file && <div className="panel-actions">
            <select aria-label="File version" className="simple-select" value={current} onChange={event => {setDependency(null); setVersion(Number(event.target.value))}}>{file.versions.map(v => <option key={v} value={v}>Version {v}</option>)}</select>
            <button className={`icon-button ${compare ? 'selected' : ''}`} title="Compare with previous version" disabled={!current || current < 2} onClick={() => setCompare(!compare)}><GitCompareArrows size={17}/></button>
            <button className="icon-button" title="Download artifact" disabled={!shown} onClick={download}><ArrowDownToLine size={17}/></button>
          </div>}
        </header>
        {error && <p className="inline-error">{error}</p>}
        {shown && compare && current && current > 1 ? <pre className="code-preview diff-preview">
          {diff.length ? diff.map((line, index) => <span key={index} className={line.startsWith('+') ? 'diff-add' : line.startsWith('-') ? 'diff-remove' : ''}>{line}{'\n'}</span>) : 'No differences between these versions.'}
        </pre> : shown && shown.path.endsWith('.svg') && typeof shown.body === 'string' ?
          <div className="svg-preview"><img alt="Exported floor plan" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(shown.body)}`}/></div> :
          <pre className="code-preview">{shown ? typeof shown.body === 'string' ? shown.body : JSON.stringify(shown.body, null, 2) : file ? 'Loading preview…' : 'Select a file to preview its contents.'}</pre>}
        {shown && <footer className="artifact-meta">
          <span><Check size={14}/> SHA-256 {shown.sha.slice(0, 10)}…</span>
          {shown.inputs.map(input => <button className="text-button" key={`${input.artifact_id}-${input.version}`} onClick={() => {setDependency(input); setVersion(0); setActive(input.artifact_id)}}
            disabled={!files.some(entry => entry.id === input.artifact_id)}><ArrowLeft size={12}/> {input.artifact_id} v{input.version}</button>)}
        </footer>}
      </section>
      <section className="panel file-activity">
        <header className="panel-header"><div className="panel-heading"><span className="panel-icon"><History size={17}/></span><div><h2>File activity</h2><p>Recorded reads and writes</p></div></div></header>
        {activity.length ? activity.map(event => <div className="activity-row" key={event.event_id}>
          <span className={`badge ${event.type.endsWith('written') ? 'warn' : 'quiet'}`}>{event.type.endsWith('written') ? 'WRITE' : 'READ'}</span>
          <div><strong>{event.actor}</strong><p>{event.payload.summary}</p></div><time>{eventTime(event.timestamp)}</time>
        </div>) : <p className="small-empty">No recorded activity for this file.</p>}
      </section>
    </div>
  </div>
}
