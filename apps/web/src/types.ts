export const roles = ['client_a', 'client_b', 'budget', 'design'] as const
export type Role = typeof roles[number]
export type Actor = Role | 'overview'
export type Action = 'approve' | 'reject' | 'request_changes'
export type Page = 'overview' | 'workspace' | 'approvals' | 'timeline'
export type Health = {mode: 'demo' | 'live'; model: string; gmi_configured: boolean; default_project_id: string}
export type Brief = {style: string; island: string; priority: string; seating: number; storage: string}
export type Draft = {seq: number; brief: Brief}
export type Proposal = {
  id: string; kind: 'tradeoff' | 'final'; version: number; status: string; required: Role[];
  decisions: Partial<Record<Role, {action: Action}>>; plan_version: number;
  label: string; summary: string; savings?: number; projected_total?: number
}
export type RoomState = {
  phase: string; confirmed_clients: Role[]; brief_version: number; plan_version: number; estimate_version: number;
  budget_stale: boolean; negotiation: Proposal | null; review: Proposal | null; approved_plan_version: number | null
}
export type Project = {
  id: string; name: string; budget: number; actor: Actor; state: RoomState;
  drafts: Partial<Record<Role, Draft>>; participants: Record<Role, string>; suggested_messages: Partial<Record<Role, string>>
  active_runs: {id: string; kind: string; status: string; stage: string}[]
}
export type EventPayload = {
  role?: Role; content?: string; speaker?: 'human' | 'agent'; summary?: string; recipient?: string;
  tool?: string; artifact_id?: string; path?: string; status?: string; operations?: Operation[];
  plan_version?: number; batch_index?: number; batch_size?: number; checks?: Check[]
}
export type RoomEvent = {
  seq: number; event_id: string; run_id: string; actor: string; type: string; visibility: string; timestamp: string; payload: EventPayload
}
export type Ref = {artifact_id: string; version: number}
export type Artifact<T = unknown> = {
  id: string; version: number; versions: number[]; path: string; sha: string; event_seq: number;
  inputs: Ref[]; status: string; owner: string; body: T
}
export type Operation = {op: 'add' | 'update' | 'remove'; object_id: string; object?: PlanObject; changes?: Partial<PlanObject>}
export type Point = [number, number]
export type PlanObject = {
  id: string; type: 'island' | 'kitchen' | 'table' | 'storage'; label: string; center_mm: Point;
  width_mm: number; depth_mm: number; height_mm: number; rotation_deg: number; seats: number;
  catalog_id: string; material_id: string
}
export type Feature = {type: 'door'; id: string; hinge_mm: Point; width_mm: number; swing_deg: number}
  | {type: 'window'; id: string; start_mm: Point; end_mm: Point}
export type Plan = {plan_id: string; plan_version: number; space: {polygon_mm: Point[]; measurement_status: string}; fixed_features: Feature[]; objects: PlanObject[]}
export type Check = {rule_id: string; object_ids: string[]; message: string; measured_mm?: number; required_mm?: number}
export type Validation = {
  status: 'passed' | 'failed' | 'needs_measurement'; plan_version: number; ruleset_version: string;
  checks: Check[]; clearances: {object_ids: string[]; measured_mm: number; required_mm: number}[]; unverified: string[]
}
export type Estimate = {estimated_total: number; remaining: number; source_plan_version: number; bom_version: number; price_catalog_version: number}
export type StyleBoard = {direction: string; materials: Record<string, {label: string; hex: string}>}
export type RunStatus = {id: string; status: string; error: string | null}
export const roleLabels: Record<Role, {role: string; agent: string; initials: string; tone: string}> = {
  client_a: {role: 'Client', agent: 'Requirement Agent', initials: 'AM', tone: 'rose'},
  client_b: {role: 'Client', agent: 'Requirement Agent', initials: 'MC', tone: 'peach'},
  budget: {role: 'Budget designer', agent: 'Budget Agent', initials: 'JL', tone: 'sage'},
  design: {role: 'Space designer', agent: 'Design Agent', initials: 'SR', tone: 'lavender'},
}
export const money = (value: number) => `NT$ ${Math.abs(value).toLocaleString('en-US')}`
export const eventTime = (value: string) => new Date(value).toLocaleTimeString('en-US', {hour: '2-digit', minute: '2-digit', hour12: false})
