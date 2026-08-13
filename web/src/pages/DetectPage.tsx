import { useCallback, useEffect, useRef, useState } from 'react'
import { FileImageIcon, UploadIcon, XIcon } from 'lucide-react'
import { runDetection } from '@/lib/sse'
import type { CvPayload, TraceEvent, VerdictPayload } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { TraceView } from '@/components/TraceView'

type Status = 'idle' | 'running' | 'done' | 'error'

const MODES = [
  { id: 'agent', label: 'Agent 复核', hint: '像素取证 + 大模型多轮查证，最完整' },
  { id: 'direct', label: '快速复核', hint: '像素取证 + 大模型单轮判读' },
  { id: 'cv', label: '仅像素取证', hint: '只跑 TruFor，不调用大模型，最快' },
] as const

/** 与后端 config.MAX_SIZE 一致：超过即走切片推理，耗时量级差约 8 倍 */
const TILED_THRESHOLD = 1792

export default function DetectPage() {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string>('')
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null)
  const [mode, setMode] = useState<string>('agent')
  const [status, setStatus] = useState<Status>('idle')
  const [events, setEvents] = useState<TraceEvent[]>([])
  const [error, setError] = useState('')
  const [durationMs, setDurationMs] = useState(0)
  const [dragging, setDragging] = useState(false)
  const abortRef = useRef<(() => void) | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // 预览 URL 是 blob:，不主动 revoke 会一直占着内存
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])

  const accept = useCallback((f: File | undefined | null) => {
    if (!f) return
    if (!f.type.startsWith('image/')) { setError('请上传图片文件（JPG/PNG/HEIC）'); return }
    setPreview((old) => { if (old) URL.revokeObjectURL(old); return URL.createObjectURL(f) })
    setFile(f)
    setDims(null)
    setEvents([])
    setStatus('idle')
    setError('')
  }, [])

  const start = () => {
    if (!file) return
    setEvents([]); setError(''); setStatus('running'); setDurationMs(0)
    abortRef.current = runDetection(file, mode, {
      onTrace: (e) => setEvents((prev) => [...prev, e]),
      onDone: (d) => { setDurationMs(d.duration_ms); setStatus('done') },
      onError: (msg) => { setError(msg); setStatus('error') },
    })
  }

  const cancel = () => { abortRef.current?.(); setStatus('idle') }

  const cv = events.find((e) => e.type === 'cv')?.payload as CvPayload | undefined
  const verdict = events.find((e) => e.type === 'verdict')?.payload as VerdictPayload | undefined
  const tiled = dims ? Math.max(dims.w, dims.h) > TILED_THRESHOLD : false
  const etaHint = tiled ? '大图需切片推理，约需 1–2 分钟' : '约需 10 秒'

  return (
    <div className="mx-auto grid max-w-[1400px] gap-6 px-6 py-6 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
      {/* 左栏：上传与图像 */}
      <section className="space-y-4">
        {!file ? (
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); accept(e.dataTransfer.files?.[0]) }}
            onClick={() => inputRef.current?.click()}
            className={`flex min-h-[380px] cursor-pointer flex-col items-center justify-center gap-3 rounded-[var(--radius)] border border-dashed px-6 text-center transition-colors ${
              dragging ? 'border-primary bg-secondary' : 'border-border-strong bg-card hover:bg-muted'
            }`}
          >
            <UploadIcon className="size-7 text-muted-foreground" />
            <div className="text-[15px]">拖拽单据图片到此处，或点击选择文件</div>
            <div className="text-xs text-muted-foreground">支持 JPG / PNG / HEIC，单张上传</div>
          </div>
        ) : (
          <div className="overflow-hidden rounded-[var(--radius)] border border-border bg-card">
            <div className="flex items-center gap-2 border-b border-border px-4 py-2.5 text-sm">
              <FileImageIcon className="size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate" title={file.name}>{file.name}</span>
              {dims && (
                <span className="num shrink-0 text-xs text-muted-foreground">
                  {dims.w}×{dims.h}{tiled && ' · 切片'}
                </span>
              )}
              <button
                onClick={() => { cancel(); setFile(null); setPreview(''); setEvents([]); setStatus('idle') }}
                className="shrink-0 rounded-[var(--radius)] p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label="移除图片"
              >
                <XIcon className="size-4" />
              </button>
            </div>
            <div className="flex min-h-[380px] items-center justify-center bg-muted p-4">
              <img
                src={preview}
                alt="待检测单据"
                className="max-h-[560px] max-w-full object-contain"
                onLoad={(e) => setDims({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
              />
            </div>
          </div>
        )}

        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => accept(e.target.files?.[0])}
        />

        {/* 模式选择 —— 静态单选，不用下拉，三个选项值得直接摊开 */}
        <fieldset className="rounded-[var(--radius)] border border-border bg-card p-3">
          <legend className="px-1 text-xs text-muted-foreground">复核模式</legend>
          <div className="flex flex-col gap-1">
            {MODES.map((m) => (
              <label
                key={m.id}
                className={`flex cursor-pointer items-start gap-2.5 rounded-[var(--radius)] px-2.5 py-2 text-sm ${
                  mode === m.id ? 'bg-secondary text-secondary-foreground' : 'hover:bg-muted'
                }`}
              >
                <input
                  type="radio"
                  name="mode"
                  value={m.id}
                  checked={mode === m.id}
                  disabled={status === 'running'}
                  onChange={() => setMode(m.id)}
                  className="mt-1 accent-[var(--accent)]"
                />
                <span className="min-w-0">
                  <span className="block font-medium">{m.label}</span>
                  <span className="block text-xs text-muted-foreground">{m.hint}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="flex items-center gap-3">
          {status === 'running' ? (
            <Button variant="outline" onClick={cancel}>中止检测</Button>
          ) : (
            <Button disabled={!file} onClick={start}>开始检测</Button>
          )}
          {file && status === 'idle' && (
            <span className="text-xs text-muted-foreground">预计{etaHint}</span>
          )}
          {status === 'running' && (
            <span className="text-xs text-muted-foreground">检测中，{etaHint}</span>
          )}
          {status === 'done' && (
            <span className="num text-xs text-muted-foreground">
              完成，耗时 {(durationMs / 1000).toFixed(1)}s
            </span>
          )}
        </div>

        {error && (
          <div className="rounded-[var(--radius)] border border-danger bg-danger-bg px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}
      </section>

      {/* 右栏：结论与轨迹（Task 7/8 填充） */}
      <section className="space-y-4">
        {status === 'idle' && !file && (
          <div className="rounded-[var(--radius)] border border-border bg-card px-5 py-6 text-sm text-muted-foreground">
            上传单据后开始检测，此处显示审核结论与复核轨迹。
          </div>
        )}
        {cv && (
          <div className="num rounded-[var(--radius)] border border-border bg-card px-4 py-3 text-sm">
            CV 置信度 {cv.score.toFixed(4)} · 推理尺寸 {cv.infer_size} · 候选区 {cv.candidates.length}
          </div>
        )}
        {verdict && (
          <div className="rounded-[var(--radius)] border border-border bg-card px-4 py-3 text-sm">
            {verdict.headline ?? verdict.text}
          </div>
        )}
        <TraceView events={events} running={status === 'running'} />
      </section>
    </div>
  )
}
