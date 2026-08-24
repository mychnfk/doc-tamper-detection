import { useState } from 'react'
import { AlertTriangleIcon, CheckIcon, ChevronDownIcon, CircleAlertIcon, HelpCircleIcon } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { VerdictPayload } from '@/lib/types'

/** 风险三态 → 语义色 + 静态字形。禁止动画点/脉冲圆（禁令 4）。CvFirstCheck 复用。 */
export const RISK = {
  低: { icon: CheckIcon, fg: 'text-ok', bg: 'bg-ok-bg', border: 'border-ok' },
  中: { icon: AlertTriangleIcon, fg: 'text-warn', bg: 'bg-warn-bg', border: 'border-warn' },
  高: { icon: CircleAlertIcon, fg: 'text-danger', bg: 'bg-danger-bg', border: 'border-danger' },
} as const

const SOURCE_LABEL: Record<string, string> = {
  agent: 'Agent 多轮复核',
  'agent-forced': 'Agent 复核（达轮次上限后收敛）',
  direct: '大模型单轮判读',
  // 不写"大模型不可用"：主动选「仅像素取证」时也走这条 source，那不是故障
  cv: '仅像素取证（TruFor）',
}

/** 结论卡片正文用的 markdown 样式——不引 typography 插件，只定这几个标签。
 *  h3 必须放大：cv/direct 链路整段走这里，标题若与正文同号，结论就不成其为视觉中心。 */
const MD = {
  p: (p: object) => <p className="mb-1.5 leading-relaxed last:mb-0" {...p} />,
  strong: (p: object) => <strong className="font-medium text-foreground" {...p} />,
  h3: (p: object) => <h3 className="mb-2 text-[19px] font-medium leading-tight" {...p} />,
  ul: (p: object) => <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0" {...p} />,
  code: (p: object) => <code className="num rounded-[var(--radius)] bg-muted px-1 py-0.5 text-[12px]" {...p} />,
}

export function VerdictCard({ payload }: { payload: VerdictPayload }) {
  const [open, setOpen] = useState(false)
  const v = payload.verdict
  const risk = (v?.risk ?? '') as keyof typeof RISK
  const style = RISK[risk] ?? { icon: HelpCircleIcon, fg: 'text-muted-foreground', bg: 'bg-muted', border: 'border-border-strong' }
  const Icon = style.icon

  // direct / cv 链路没有结构化字段，只能整段渲染 text（与后端 app.py 的分支一致）
  const structured = Boolean(v)

  return (
    <div className={`dg-verdict overflow-hidden rounded-[var(--radius)] border ${style.border}`}>
      <div className={`${style.bg} px-5 py-4`}>
        {structured ? (
          <>
            <div className="flex items-start gap-2.5">
              <Icon className={`mt-0.5 size-5 shrink-0 ${style.fg}`} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="text-[19px] font-medium leading-tight">{v!.conclusion}</span>
                  <span className={`text-sm ${style.fg}`}>风险 {v!.risk}</span>
                </div>
                {v!.advice && (
                  <div className="mt-1.5 text-sm text-foreground">
                    <span className="text-muted-foreground">建议操作：</span>{v!.advice}
                  </div>
                )}
              </div>
            </div>
          </>
        ) : (
          <div className="flex items-start gap-2.5">
            <Icon className={`mt-0.5 size-5 shrink-0 ${style.fg}`} />
            <div className="min-w-0 flex-1 text-sm">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD}>{payload.text}</ReactMarkdown>
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-inherit bg-card px-5 py-2">
        {structured ? (
          <button
            onClick={() => setOpen((o) => !o)}
            className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
            aria-expanded={open}
          >
            为什么这么判
            <ChevronDownIcon className={`size-4 ${open ? 'rotate-180' : ''}`} />
          </button>
        ) : <span />}
        <span className="text-xs text-muted-foreground">{SOURCE_LABEL[payload.source] ?? payload.source}</span>
      </div>

      {structured && open && (
        <div className="space-y-3 border-t border-border bg-card px-5 py-4 text-sm">
          <div>
            <div className="mb-1 text-xs text-muted-foreground">异常区域</div>
            <div className="leading-relaxed">{v!.regions || '无'}</div>
          </div>
          <div>
            <div className="mb-1 text-xs text-muted-foreground">复核依据</div>
            <div className="leading-relaxed">{v!.basis || '—'}</div>
          </div>
        </div>
      )}
    </div>
  )
}
