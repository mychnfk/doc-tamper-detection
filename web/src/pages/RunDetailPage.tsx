import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeftIcon } from 'lucide-react'
import type { CvPayload, TraceEvent, VerdictPayload } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { TraceView } from '@/components/TraceView'
import { VerdictCard } from '@/components/VerdictCard'
import { CompareSlider } from '@/components/CompareSlider'
import { TechDetails } from '@/components/TechDetails'

type RunDetail = {
  meta: {
    run_id: string
    image_name: string
    mode: string
    created_at: string
    conclusion?: string
    risk?: string
    score?: number
    infer_size?: string
    duration_ms?: number
  }
  events: TraceEvent[]
}

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [run, setRun] = useState<RunDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    if (!id) return
    setLoading(true)
    fetch(`/api/runs/${id}`)
      .then((r) => {
        if (!r.ok) throw new Error(r.status === 404 ? '记录不存在' : '加载失败')
        return r.json()
      })
      .then(setRun)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="text-sm text-muted-foreground">加载中…</div>
      </div>
    )
  }

  if (error || !run) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3">
        <div className="text-sm text-danger">{error || '记录不存在'}</div>
        <Button variant="outline" size="sm" onClick={() => navigate('/runs')}>返回列表</Button>
      </div>
    )
  }

  const cv = run.events.find((e) => e.type === 'cv')?.payload as CvPayload | undefined
  const verdict = run.events.find((e) => e.type === 'verdict')?.payload as VerdictPayload | undefined

  return (
    <div className="mx-auto max-w-[1400px] space-y-4 px-6 py-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => navigate('/runs')}>
          <ArrowLeftIcon className="size-4" />
          返回列表
        </Button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-lg font-medium" title={run.meta.image_name}>
            {run.meta.image_name}
          </div>
          <div className="text-xs text-muted-foreground">
            {new Date(run.meta.created_at).toLocaleString('zh-CN')}
            {run.meta.duration_ms && (
              <span className="num"> · 耗时 {(run.meta.duration_ms / 1000).toFixed(1)}s</span>
            )}
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <section className="space-y-4 lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:self-start lg:overflow-y-auto">
          {verdict && <VerdictCard payload={verdict} />}

          {cv && (
            <>
              <CompareSlider
                original={cv.original}
                heatmap={cv.heatmap}
              />
              <TechDetails cv={cv} durationMs={run.meta.duration_ms ?? 0} />
            </>
          )}
        </section>

        <section>
          <TraceView events={run.events} running={false} mode={run.meta.mode} />
        </section>
      </div>
    </div>
  )
}
