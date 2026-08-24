import { useState } from 'react'
import {
  AlertTriangleIcon, BrainIcon, ChevronDownIcon, CircleDashedIcon, ScanSearchIcon,
  SearchIcon, WrenchIcon,
} from 'lucide-react'
import {
  ChainOfThought, ChainOfThoughtImage, ChainOfThoughtSearchResult,
  ChainOfThoughtSearchResults, ChainOfThoughtStep,
} from '@/components/ai-elements/chain-of-thought'
import type {
  FallbackPayload, StagePayload, ThoughtPayload,
  ToolCallPayload, ToolResultPayload, TraceEvent,
} from '@/lib/types'

const STAGE_LABEL: Record<string, string> = { vlm_review: '智能复核' }
const TOOL_LABEL: Record<string, string> = {
  zoom_region: '放大可疑区域',
  second_opinion: '第二模型交叉验证',
}

/** 降级提示：原始异常默认收起。
 *  坑 #8 的回归点——Gradio 版曾因未设 status 让技术详情默认展开，把栈信息糊在评委脸上。 */
function FallbackNotice({ p }: { p: FallbackPayload }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-[var(--radius)] border border-warn bg-warn-bg px-3 py-2.5 text-sm text-warn">
      <div className="flex items-start gap-2">
        <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" />
        <div className="min-w-0 flex-1">
          <div>{p.reason}</div>
          {p.detail && (
            <>
              <button
                onClick={() => setOpen((v) => !v)}
                className="mt-1.5 flex items-center gap-1 text-xs underline-offset-2 hover:underline"
                aria-expanded={open}
              >
                技术详情
                <ChevronDownIcon className={`size-3 ${open ? 'rotate-180' : ''}`} />
              </button>
              {open && (
                <pre className="mt-1.5 overflow-x-auto whitespace-pre-wrap break-all rounded-[var(--radius)] bg-muted px-2.5 py-2 font-mono text-[11px] text-muted-foreground">
                  {p.detail}
                </pre>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function secs(ms: number) {
  return `${(ms / 1000).toFixed(1)}s`
}

/** 等待期把整条流程摊开（spec §6.3）：只显示一个转圈会让人不知道还剩几步 */
const PLAN: Record<string, string[]> = {
  agent: ['像素级取证（TruFor）', '大模型研判可疑区域', '调用工具放大查证', '出具审核结论'],
  direct: ['像素级取证（TruFor）', '大模型单轮判读', '出具审核结论'],
  cv: ['像素级取证（TruFor）', '按阈值给出判定'],
}

export function TraceView(
  { events, running, mode }: { events: TraceEvent[]; running: boolean; mode: string },
) {
  // verdict 交给 VerdictCard，cv 交给 TechDetails，此处只渲染过程
  const steps = events.filter((e) => e.type !== 'verdict' && e.type !== 'cv')
  if (steps.length === 0 && !running) return null

  const hasCv = events.some((e) => e.type === 'cv')
  const plan = PLAN[mode] ?? PLAN.agent

  return (
    <div className="rounded-[var(--radius)] border border-border bg-card">
      <div className="border-b border-border px-4 py-2.5 text-sm font-medium">审核轨迹</div>
      <div className="px-4 py-4">
        <ChainOfThought>
          {steps.map((e, i) => {
            // staggered 流入，单条 ≤160ms（spec §5.2）；封顶 6 条，否则末尾条目要等太久
            const style = { animationDelay: `${Math.min(i, 6) * 40}ms` }
            const key = `${e.turn}-${e.type}-${i}`

            if (e.type === 'stage') {
              const p = e.payload as unknown as StagePayload
              return (
                <ChainOfThoughtStep
                  key={key} className="dg-step" style={style}
                  icon={ScanSearchIcon}
                  label={STAGE_LABEL[p.stage] ?? p.stage}
                  description={`模式 ${p.mode} · 像素取证已完成，用时 ${secs(e.elapsed_ms)}`}
                  status="complete"
                />
              )
            }

            if (e.type === 'thought') {
              const p = e.payload as unknown as ThoughtPayload
              return (
                <ChainOfThoughtStep
                  key={key} className="dg-step" style={style}
                  icon={BrainIcon}
                  label={`第 ${e.turn} 轮 · 思考`}
                  description={secs(e.elapsed_ms)}
                  status="complete"
                >
                  <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-foreground">
                    {p.thought}
                  </p>
                </ChainOfThoughtStep>
              )
            }

            if (e.type === 'tool_call') {
              const p = e.payload as unknown as ToolCallPayload
              const args = Object.entries(p.args ?? {})
              return (
                <ChainOfThoughtStep
                  key={key} className="dg-step" style={style}
                  icon={WrenchIcon}
                  label={`第 ${e.turn} 轮 · ${TOOL_LABEL[p.tool] ?? p.tool}`}
                  status="complete"
                >
                  {args.length > 0 && (
                    <ChainOfThoughtSearchResults>
                      {args.map(([k, v]) => (
                        <ChainOfThoughtSearchResult key={k} className="num">
                          {k}={String(v)}
                        </ChainOfThoughtSearchResult>
                      ))}
                    </ChainOfThoughtSearchResults>
                  )}
                </ChainOfThoughtStep>
              )
            }

            if (e.type === 'tool_result') {
              const p = e.payload as unknown as ToolResultPayload
              return (
                <ChainOfThoughtStep
                  key={key} className="dg-step" style={style}
                  icon={SearchIcon}
                  label={`第 ${e.turn} 轮 · 查证结果`}
                  description={secs(e.elapsed_ms)}
                  status={p.error ? 'pending' : 'complete'}
                >
                  <p className={`text-[13px] leading-relaxed ${p.error ? 'text-danger' : 'text-muted-foreground'}`}>
                    {p.text}
                  </p>
                  {p.images?.map((src) => (
                    <ChainOfThoughtImage key={src} className="rounded-[var(--radius)]" caption="放大后的可疑区域">
                      <img src={src} alt="放大后的可疑区域" className="max-h-[18rem] object-contain" />
                    </ChainOfThoughtImage>
                  ))}
                </ChainOfThoughtStep>
              )
            }

            if (e.type === 'fallback') {
              return (
                <div key={key} className="dg-step" style={style}>
                  <FallbackNotice p={e.payload as unknown as FallbackPayload} />
                </div>
              )
            }
            return null
          })}

          {running && (
            /* 等待期占位：静态字形 + 文字，不用动画点/脉冲圆（禁令 4）。
               当前步骤 active，后续步骤 pending 淡显，让人知道还剩几步。 */
            <>
              <ChainOfThoughtStep
                icon={hasCv ? BrainIcon : ScanSearchIcon}
                label={hasCv ? '大模型复核中…' : '像素级取证中…'}
                description="正在进行"
                status="active"
              />
              {plan.slice(hasCv ? 2 : 1).map((s) => (
                <ChainOfThoughtStep key={s} icon={CircleDashedIcon} label={s} status="pending" />
              ))}
            </>
          )}
        </ChainOfThought>
      </div>
    </div>
  )
}
