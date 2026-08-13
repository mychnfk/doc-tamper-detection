import { useState } from 'react'
import { ChevronDownIcon } from 'lucide-react'
import type { CvPayload } from '@/lib/types'

/** 渐进式披露第三层：默认收起。评委想深挖时才展开，不占视觉中心。 */
export function TechDetails({ cv, durationMs }: { cv: CvPayload; durationMs: number }) {
  const [open, setOpen] = useState(false)
  const tiled = cv.infer_size.includes('tiled')

  return (
    <div className="rounded-[var(--radius)] border border-border bg-card">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm hover:bg-muted"
        aria-expanded={open}
      >
        <ChevronDownIcon className={`size-4 shrink-0 text-muted-foreground ${open ? 'rotate-180' : '-rotate-90'}`} />
        <span className="font-medium">技术细节</span>
        <span className="num min-w-0 flex-1 truncate text-xs text-muted-foreground">
          分数 {cv.score.toFixed(4)} · {cv.infer_size} · 候选区 {cv.candidates.length}
          {durationMs > 0 && ` · 总耗时 ${(durationMs / 1000).toFixed(1)}s`}
        </span>
      </button>

      {open && (
        <div className="space-y-4 border-t border-border px-4 py-4">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">CV 置信度</dt>
              <dd className="num">{cv.score.toFixed(4)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">推理尺寸</dt>
              <dd className="num">{cv.infer_size}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">推理方式</dt>
              <dd>{tiled ? '切片推理' : '整图推理'}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">总耗时</dt>
              <dd className="num">{(durationMs / 1000).toFixed(1)}s</dd>
            </div>
          </dl>

          <div>
            <div className="mb-2 text-xs text-muted-foreground">候选可疑区域</div>
            {cv.candidates.length === 0 ? (
              <div className="text-sm text-muted-foreground">未提取到候选区域</div>
            ) : (
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="py-1.5 pr-3 font-normal">#</th>
                    <th className="py-1.5 pr-3 font-normal">bbox (x1,y1,x2,y2)</th>
                    <th className="py-1.5 pr-3 font-normal">面积占比</th>
                    <th className="py-1.5 font-normal">区域均分</th>
                  </tr>
                </thead>
                <tbody>
                  {cv.candidates.map((c) => (
                    <tr key={c.id} className="border-b border-border last:border-0">
                      <td className="py-1.5 pr-3">{c.id}</td>
                      <td className="py-1.5 pr-3">{c.bbox.join(', ')}</td>
                      <td className="py-1.5 pr-3">{(c.area_frac * 100).toFixed(2)}%</td>
                      <td className="py-1.5">{c.mean_score.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div>
            <div className="mb-2 text-xs text-muted-foreground">置信度图（越亮表示该处判定越可信）</div>
            <img
              src={cv.confidence}
              alt="TruFor 置信度图"
              className="max-h-[16rem] rounded-[var(--radius)] border border-border object-contain"
            />
          </div>
        </div>
      )}
    </div>
  )
}
