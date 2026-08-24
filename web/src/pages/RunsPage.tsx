import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ClockIcon, FileTextIcon, Trash2Icon } from 'lucide-react'
import { Button } from '@/components/ui/button'

type RunMeta = {
  run_id: string
  image_name: string
  mode: string
  created_at: string
  conclusion?: string
  risk?: string
  score?: number
  duration_ms?: number
}

const MODE_LABEL: Record<string, string> = {
  agent: 'Agent 复核',
  direct: '快速复核',
  cv: '仅像素取证',
}

const RISK_COLOR: Record<string, string> = {
  低: 'text-success',
  中: 'text-warn',
  高: 'text-danger',
}

export default function RunsPage() {
  const [runs, setRuns] = useState<RunMeta[]>([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  const load = async () => {
    setLoading(true)
    const r = await fetch('/api/runs')
    const data = await r.json()
    setRuns(data.runs ?? [])
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const del = async (id: string) => {
    if (!confirm('确认删除此记录？')) return
    await fetch(`/api/runs/${id}`, { method: 'DELETE' })
    load()
  }

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="text-sm text-muted-foreground">加载中…</div>
      </div>
    )
  }

  if (runs.length === 0) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3">
        <FileTextIcon className="size-8 text-muted-foreground" />
        <div className="text-sm text-muted-foreground">暂无检测记录</div>
        <Button size="sm" onClick={() => navigate('/detect')}>开始检测</Button>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4 px-6 py-6">
      <h1 className="text-xl font-medium">检测记录</h1>

      <div className="space-y-2">
        {runs.map((run) => (
          <div
            key={run.run_id}
            className="group overflow-hidden rounded-[var(--radius)] border border-border bg-card transition-colors hover:bg-muted"
          >
            <button
              onClick={() => navigate(`/runs/${run.run_id}`)}
              className="w-full px-4 py-3 text-left"
            >
              <div className="flex items-start gap-3">
                <FileTextIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="truncate font-medium" title={run.image_name}>
                      {run.image_name}
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {MODE_LABEL[run.mode] ?? run.mode}
                    </span>
                  </div>

                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <ClockIcon className="size-3" />
                      {new Date(run.created_at).toLocaleString('zh-CN', {
                        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                      })}
                    </span>

                    {run.conclusion && (
                      <span>
                        结论 <span className="text-foreground">{run.conclusion}</span>
                      </span>
                    )}

                    {run.risk && (
                      <span>
                        风险 <span className={RISK_COLOR[run.risk] ?? 'text-foreground'}>{run.risk}</span>
                      </span>
                    )}

                    {run.score !== undefined && (
                      <span className="num">
                        像素得分 <span className="text-foreground">{run.score.toFixed(4)}</span>
                      </span>
                    )}

                    {run.duration_ms && (
                      <span className="num">
                        耗时 {(run.duration_ms / 1000).toFixed(1)}s
                      </span>
                    )}
                  </div>
                </div>

                <button
                  onClick={(e) => { e.stopPropagation(); del(run.run_id) }}
                  className="shrink-0 rounded-[var(--radius)] p-1.5 text-muted-foreground opacity-0 transition-opacity hover:bg-danger-bg hover:text-danger group-hover:opacity-100"
                  aria-label="删除"
                >
                  <Trash2Icon className="size-4" />
                </button>
              </div>
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
