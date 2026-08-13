// 与后端字段一一对应；改这里之前先看 agent.py 的 TraceEvent 构造点与 api.py::serialize_event
export type TraceType =
  | 'cv' | 'stage' | 'thought' | 'tool_call' | 'tool_result' | 'verdict' | 'fallback'

/** 结论来源。cv/direct 两种不带结构化 verdict，只有 text（见 agent.py::_cv_only_verdict）。 */
export type VerdictSource = 'agent' | 'agent-forced' | 'direct' | 'cv'

export interface TraceEvent {
  run_id: string
  turn: number
  type: TraceType
  elapsed_ms: number
  payload: Record<string, unknown>
}

export interface CvPayload {
  score: number
  infer_size: string
  candidates: { id: number; bbox: number[]; area_frac: number; mean_score: number }[]
  original: string
  heatmap: string
  confidence: string
}

export interface StagePayload {
  stage: string
  mode: string
}

export interface ThoughtPayload {
  thought: string
}

export interface ToolCallPayload {
  tool: string
  args: Record<string, unknown>
}

export interface ToolResultPayload {
  tool: string
  text: string
  images: string[]        // api.py 已把 PIL 图落盘换成 /api/runs/... URL
  error: boolean
}

export interface FallbackPayload {
  reason: string          // 面向用户的说法
  detail: string          // 原始异常，只在技术细节里展示
}

export interface VerdictPayload {
  /** agent 模式才有结构化字段；direct/cv 为 null，此时只能渲染 text。 */
  verdict: { conclusion: string; risk: string; regions?: string; basis?: string; advice?: string } | null
  text: string
  headline?: string
  detail?: string
  source: VerdictSource
}

export interface RunMeta {
  run_id: string
  image_name: string
  mode: 'agent' | 'direct' | 'cv'
  created_at: string
  score?: number
  infer_size?: string
  conclusion?: string
  risk?: string
  source?: VerdictSource
  duration_ms?: number
  error?: string
}
