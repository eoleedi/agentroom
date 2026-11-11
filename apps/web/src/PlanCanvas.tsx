import {useId, useState} from 'react'
import {ArrowDownLeft, Check, ChevronDown, Focus, Layers3, Maximize, Minus, Plus, Ruler, ScanLine} from './icons'
import {errorText} from './api'
import type {Operation, Plan, PlanObject} from './types'

const fills = {kitchen: 'cabinet', island: 'oak', table: 'walnut', storage: 'sage'} as const
const objectNames = {kitchen: 'KITCHEN RUN', island: 'ISLAND', table: 'DINING FOR SIX', storage: 'LOW STORAGE'} as const

function Furniture({obj, palette, selected, changed, onSelect}: {obj: PlanObject; palette: string; selected: boolean; changed: boolean; onSelect: () => void}) {
  const [x, y] = obj.center_mm
  const w = obj.width_mm, d = obj.depth_mm
  const dining = obj.type === 'table'
  const chairPositions = [[-480, -570, 0], [480, -570, 0], [-480, 570, 180], [480, 570, 180], [-1020, 0, -90], [1020, 0, 90]]
  return <g className="furniture" tabIndex={0} role="button" aria-label={obj.label} aria-pressed={selected}
    onClick={onSelect} onKeyDown={event => {if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); onSelect()}}}
    transform={`translate(${x} ${y}) rotate(${obj.rotation_deg})`}>
    {dining && chairPositions.map(([cx, cy, angle]) => <g key={`${cx}-${cy}`} transform={`translate(${cx} ${cy}) rotate(${angle})`}>
      <rect x="-200" y="-170" width="400" height="340" rx="85" fill="#d6c3aa" stroke="#826b54" strokeWidth="17"/>
      <path d="M -145 -165 Q 0 -228 145 -165" fill="none" stroke="#80664c" strokeWidth="26"/>
    </g>)}
    <rect className="object-shadow" x={-w / 2 + 43} y={-d / 2 + 55} width={w} height={d} rx={obj.type === 'kitchen' ? 14 : 55} fill="#7b5941" opacity=".13"/>
    <rect x={-w / 2} y={-d / 2} width={w} height={d} rx={obj.type === 'kitchen' ? 14 : 55}
      fill={`url(#${palette}-${fills[obj.type]})`} stroke={selected || changed ? '#a34e32' : '#6e6455'}
      strokeWidth={selected || changed ? 44 : 20}/>
    {obj.type === 'kitchen' && <>
      {[-1665, -830, 0, 830, 1665].map(dx => <path key={dx} d={`M${dx} -350v700`} stroke="#978a72" strokeWidth="15"/>)}
      <rect x="-2220" y="-185" width="560" height="370" rx="55" fill="#e4dfcf" stroke="#8d8270" strokeWidth="18"/>
      <rect x="-2180" y="-143" width="220" height="286" rx="38" fill="none" stroke="#ada48f" strokeWidth="12"/>
      <rect x="-1920" y="-143" width="220" height="286" rx="38" fill="none" stroke="#ada48f" strokeWidth="12"/>
      <rect x="1450" y="-236" width="670" height="472" rx="38" fill="#534a42"/>
      {[1555, 1785, 2015].flatMap(cx => [-110, 110].map(cy => <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="65" fill="none" stroke="#bcb3a5" strokeWidth="12"/>))}
    </>}
    {obj.type === 'island' && <path d={`M${-w / 2 + 100} ${d / 2 - 125}h${w - 200}`} stroke="#a77e55" strokeWidth="22"/>}
    {obj.type === 'storage' && [-300, 300].map(dx => <path key={dx} d={`M${dx} -250v500`} stroke="#6b7460" strokeWidth="16"/>)}
    <text className="furniture-label" textAnchor="middle" y={obj.type === 'kitchen' || obj.type === 'storage' ? 49 : -10}
      fill={dining ? '#fff8eb' : '#32291f'}>{objectNames[obj.type]}</text>
    {(dining || obj.type === 'island') && <text className="furniture-size" textAnchor="middle" y="170"
      fill={dining ? '#efe4d6' : '#514133'}>{obj.width_mm} × {obj.depth_mm}</text>}
  </g>
}

function Dimension({x1, y1, x2, y2, label, vertical = false}: {x1: number; y1: number; x2: number; y2: number; label: string; vertical?: boolean}) {
  const x = (x1+x2)/2, y = (y1+y2)/2
  return <g className="dimension">
    <path d={`M${x1} ${y1}L${x2} ${y2} M${x1-70} ${y1+70}l140 -140 M${x2-70} ${y2+70}l140 -140`}/>
    <text x={vertical ? x-105 : x} y={vertical ? y : y-93} transform={vertical ? `rotate(-90 ${x-105} ${y})` : undefined}>{label}</text>
  </g>
}

export function PlanCanvas({plan, selected, changed, onSelect, dimensions, zones, zoom, offset, setOffset, setZoom}: {
  plan: Plan; selected: string[]; changed: string[]; onSelect: (id: string) => void; dimensions: boolean; zones: boolean;
  zoom: number; offset: [number, number]; setOffset: (value: [number, number]) => void; setZoom: (zoom: number) => void
}) {
  const palette = useId().replaceAll(':', '')
  const [drag, setDrag] = useState<{x: number; y: number; original: [number, number]} | null>(null)
  const width = Math.max(...plan.space.polygon_mm.map(p => p[0]))
  const depth = Math.max(...plan.space.polygon_mm.map(p => p[1]))
  const boxWidth = (width + 1620) / zoom, boxHeight = (depth + 1250) / zoom
  const points = plan.space.polygon_mm.map(p => p.join(',')).join(' ')
  const door = plan.fixed_features.find(feature => feature.type === 'door')
  const table = plan.objects.find(obj => obj.type === 'table')
  const island = plan.objects.find(obj => obj.type === 'island')
  return <svg className="floor-svg" viewBox={`${width/2 - boxWidth/2 + offset[0]} ${depth/2 - boxHeight/2 + offset[1]} ${boxWidth} ${boxHeight}`}
    role="group" aria-label={`Interactive kitchen and dining floor plan version ${plan.plan_version}`}
    onPointerDown={event => {
      if ((event.target as SVGElement).closest('.furniture')) return
      event.currentTarget.setPointerCapture(event.pointerId)
      setDrag({x: event.clientX, y: event.clientY, original: offset})
    }}
    onPointerMove={event => {
      if (!drag) return
      const scale = Math.max(boxWidth / event.currentTarget.clientWidth, boxHeight / event.currentTarget.clientHeight)
      setOffset([drag.original[0] + (drag.x - event.clientX)*scale, drag.original[1] + (drag.y - event.clientY)*scale])
    }} onPointerUp={() => setDrag(null)} onPointerCancel={() => setDrag(null)}
    onDoubleClick={() => {setZoom(1); setOffset([0, 0])}}>
    <defs>
      <pattern id={`${palette}-floor`} width="540" height="180" patternUnits="userSpaceOnUse">
        <rect width="540" height="180" fill="#f5ecda"/>
        <path d="M0 0h540 M0 90h540 M120 0v90 M400 90v90" stroke="#dcccaf" strokeWidth="8" opacity=".75"/>
        <path d="M14 35h95 M167 125h188 M422 59h78" stroke="#e9d9bb" strokeWidth="12"/>
      </pattern>
      {Object.entries({cabinet: ['#d3c9b1', '#b2a78c'], oak: ['#cfa97f', '#b88e65'], walnut: ['#8c674e', '#a17e63'], sage: ['#9da58e', '#849078']}).map(([name, [color, grain]]) =>
        <pattern key={name} id={`${palette}-${name}`} width="500" height="100" patternUnits="userSpaceOnUse">
          <rect width="500" height="100" fill={color}/><path d="M0 17 Q125 27 250 17 T500 17 M0 75 Q125 60 250 75 T500 75" stroke={grain} strokeWidth="9" opacity=".65" fill="none"/>
        </pattern>)}
    </defs>
    <polygon points={points} transform="translate(60 65)" strokeWidth="150" strokeLinejoin="round" stroke="#a69780" fill="#a69780" opacity=".16"/>
    <polygon points={points} fill={`url(#${palette}-floor)`} stroke="#4d483d" strokeWidth="95" strokeLinejoin="round"/>
    <polygon points={points} fill="none" stroke="#938571" strokeWidth="18"/>
    {plan.fixed_features.filter(f => f.type === 'window').map(f => <g key={f.id}>
      <path d={`M${f.start_mm.join(' ')} L${f.end_mm.join(' ')}`} stroke="#dce1d6" strokeWidth="100"/>
      <path d={`M${f.start_mm.join(' ')} L${f.end_mm.join(' ')}`} stroke="#748477" strokeWidth="20"/>
    </g>)}
    {door && <g transform={`translate(${door.hinge_mm.join(' ')})`}>
      <path d={`M0 0v${door.width_mm}`} stroke="#f6eddb" strokeWidth="108"/>
      <path d={`M0 ${door.width_mm} A${door.width_mm} ${door.width_mm} 0 0 0 ${door.width_mm} 0`} fill="none" stroke="#988572" strokeWidth="16" strokeDasharray="50 36"/>
      <path d={`M0 0h${door.width_mm}`} stroke="#695b48" strokeWidth="36"/>
    </g>}
    {zones && table && <g transform={`translate(${table.center_mm.join(' ')}) rotate(${table.rotation_deg})`}>
      <rect x={-table.width_mm/2-650} y={-table.depth_mm/2-650} width={table.width_mm+1300} height={table.depth_mm+1300}
        fill="#aaaf8c" fillOpacity=".22" stroke="#818961" strokeWidth="20" strokeDasharray="52 38" rx="70"/>
    </g>}
    {plan.objects.map(obj => <Furniture key={obj.id} obj={obj} palette={palette} selected={selected.includes(obj.id)}
      changed={changed.includes(obj.id)} onSelect={() => onSelect(obj.id)}/>)}
    {dimensions && <>
      <Dimension x1={0} y1={-270} x2={width} y2={-270} label={`${width.toLocaleString('en-US')} mm`}/>
      <Dimension x1={-270} y1={0} x2={-270} y2={depth} label={`${depth.toLocaleString('en-US')} mm`} vertical/>
      {island && table && island.rotation_deg % 180 === 0 && table.rotation_deg % 180 === 0 && island.center_mm[1] === table.center_mm[1] && (() => {
        const left = island.center_mm[0]+island.width_mm/2, right = table.center_mm[0]-table.width_mm/2
        return right > left ? <Dimension x1={left+45} y1={island.center_mm[1]+390} x2={right-45} y2={island.center_mm[1]+390} label={`${right-left} mm`}/> : null
      })()}
    </>}
    <text x="620" y="4380" className="room-label">ENTRY</text>
    <text x="3260" y="4210" className="room-label" textAnchor="middle">KITCHEN / DINING</text>
    <path d={`M${width-1100} ${depth+300}h1000m-1000 -55v110m1000 -110v110`} stroke="#716657" strokeWidth="16"/>
    <text x={width-600} y={depth+495} className="room-label" textAnchor="middle">1 M</text>
  </svg>
}

function PlacementEditor({item, onEdit}: {item: PlanObject; onEdit: (id: string, changes: {center_mm: [number, number]; rotation_deg: number}, reason: string) => Promise<void>}) {
  const [x, setX] = useState(String(item.center_mm[0]))
  const [y, setY] = useState(String(item.center_mm[1]))
  const [rotation, setRotation] = useState(item.rotation_deg)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const unchanged = Number(x) === item.center_mm[0] && Number(y) === item.center_mm[1] && rotation === item.rotation_deg
  return <form className="placement-editor" onSubmit={event => {
    event.preventDefault()
    if (busy || unchanged || !reason.trim()) return
    setBusy(true); setError('')
    void onEdit(item.id, {center_mm: [Number(x), Number(y)], rotation_deg: rotation}, reason.trim())
      .catch(cause => setError(errorText(cause))).finally(() => setBusy(false))
  }}>
    <div className="section-copy"><h3>Edit draft placement</h3><p>{item.label} · Position at object center, in mm</p></div>
    <fieldset disabled={busy}>
      <label>X (mm)<input type="number" min="0" max="20000" step="1" required value={x} onChange={event => setX(event.target.value)}/></label>
      <label>Y (mm)<input type="number" min="0" max="20000" step="1" required value={y} onChange={event => setY(event.target.value)}/></label>
      <label>Rotation<select value={rotation} onChange={event => setRotation(Number(event.target.value))}>{[0, 90, 180, 270].map(value => <option key={value} value={value}>{value}°</option>)}</select></label>
    </fieldset>
    <label>Revision reason<input value={reason} maxLength={1000} required disabled={busy} placeholder="Explain the placement change" onChange={event => setReason(event.target.value)}/></label>
    {error && <p className="inline-error" role="alert">{error}</p>}
    <div className="placement-submit"><small>Checks geometry, updates BOM, and requests a new review.</small>
      <button className="button small primary" disabled={busy || unchanged || !reason.trim()}>{busy ? 'Validating…' : 'Validate & save draft'}</button></div>
  </form>
}

export function PlanPanel({plan, referenceOnly = false, versions, version, setVersion, operations, selected, setSelected, approved, onValidation, validation, changed, onEdit}: {
  plan: Plan | null; versions: number[]; version: number; setVersion: (value: number) => void; operations: Operation[] | null;
  selected: string[]; setSelected: (ids: string[]) => void; approved: boolean; onValidation: () => void;
  validation: boolean; changed: string[]; referenceOnly?: boolean;
  onEdit?: (id: string, changes: {center_mm: [number, number]; rotation_deg: number}, reason: string) => Promise<void>
}) {
  const [dimensions, setDimensions] = useState(true)
  const [zones, setZones] = useState(false)
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState<[number, number]>([0, 0])
  const [expanded, setExpanded] = useState(false)
  const shownPlan = plan && operations ? {...plan, objects: operations.flatMap(op => op.op === 'add' && op.object ? [op.object] : [])} : plan
  const item = plan?.objects.find(obj => selected.length === 1 && selected[0] === obj.id)
  const reset = () => {setZoom(1); setOffset([0, 0])}
  return <section className={`panel plan-panel ${expanded ? 'plan-expanded' : ''}`}>
    <header className="panel-header">
      <div className="panel-heading"><span className="panel-icon"><Layers3 size={17}/></span><div><h2>Floor plan</h2><p>Kitchen & dining</p></div></div>
      <div className="panel-actions">
        {plan && <span className={`badge ${approved ? 'good' : 'quiet'}`}>{referenceOnly ? 'Room reference · Awaiting briefs' : approved ? 'Approved' : 'Draft'}</span>}
        {versions.length > 0 && <label className="select-control"><select aria-label="Floor plan version" value={version} onChange={event => {setVersion(Number(event.target.value)); reset()}}>
          {versions.map(v => <option key={v} value={v}>Version {v}</option>)}
        </select><ChevronDown size={13}/></label>}
      </div>
    </header>
    <div className="canvas">
      <div className="canvas-top"><span className="canvas-tag"><span/> 2D PLAN</span>
        <button className="icon-button canvas-button" title={expanded ? 'Exit full view' : 'Expand floor plan'} onClick={() => setExpanded(!expanded)}>{expanded ? <ArrowDownLeft size={17}/> : <Maximize size={16}/>}</button>
      </div>
      {shownPlan ? <PlanCanvas plan={shownPlan} selected={selected} changed={changed} onSelect={id => setSelected(selected[0] === id ? [] : [id])}
        dimensions={dimensions} zones={zones} zoom={zoom} offset={offset} setOffset={setOffset} setZoom={setZoom}/>
        : <div className="empty canvas-empty"><ScanLine size={30}/><strong>No plan yet</strong><p>Confirm both briefs to generate a plan.</p></div>}
      <div className="canvas-bottom">
        <div className="canvas-tools">
          <button className={dimensions ? 'pressed' : ''} aria-pressed={dimensions} title="Toggle dimensions" onClick={() => setDimensions(!dimensions)}><Ruler size={16}/></button>
          <button className={zones ? 'pressed' : ''} aria-pressed={zones} title="Toggle seating clearance" onClick={() => setZones(!zones)}><Focus size={16}/></button>
        </div>
        <div className="canvas-tools zoom-tools">
          <button title="Zoom out" onClick={() => setZoom(Math.max(0.7, zoom-.2))}><Minus size={16}/></button>
          <button title="Reset zoom and position" onClick={reset}>{Math.round(zoom*100)}%</button>
          <button title="Zoom in" onClick={() => setZoom(Math.min(2.3, zoom+.2))}><Plus size={16}/></button>
        </div>
      </div>
    </div>
    <footer className="plan-footer">
      <span>{referenceOnly ? 'Room outline only · Furniture layout not generated' : item ? `${item.label} · ${item.width_mm.toLocaleString('en-US')} × ${item.depth_mm} mm` : 'Millimeters · Demo measurements'}</span>
      {validation && <button className="text-button success" onClick={onValidation}><Check size={15}/> Spatial checks</button>}
    </footer>
    {item && item.type !== 'kitchen' && onEdit && <PlacementEditor key={`${version}-${item.id}`} item={item} onEdit={onEdit}/>}
  </section>
}
