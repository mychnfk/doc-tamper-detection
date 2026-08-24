import { HelpCircleIcon } from 'lucide-react'
import type { CvPayload } from '@/lib/types'
import { RISK } from '@/components/VerdictCard'

/** CV 首检独立判定条 — agent/direct 模式下保留 TruFor 的自主判断，与大模型终判并列可见；
 *  也让等待 VLM 的一两分钟里先有 CV 结论可看。cv 模式不渲染（结论卡片本身就是 CV 判定）。 */
export function CvFirstCheck({ cv }: { cv: CvPayload }) {
  const style = RISK[(cv.risk ?? '') as keyof typeof RISK]
    ?? { icon: HelpCircleIcon, fg: 'text-muted-foreground', bg: 'bg-muted', border: 'border-border-strong' }
  const Icon = style.icon

  return (
    <div className={`flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[var(--radius)] border ${style.border} ${style.bg} px-4 py-2.5 text-sm`}>
      <Icon className={`size-4 shrink-0 ${style.fg}`} />
      <span className="text-muted-foreground">CV 首检</span>
      {cv.label && <span className="font-medium">{cv.label}</span>}
      <span className="num">
        篡改评分 {cv.score.toFixed(4)}
        <span className="text-xs text-muted-foreground">（0=正常，1=篡改）</span>
      </span>
      <span className="ml-auto text-xs text-muted-foreground">TruFor 像素取证</span>
    </div>
  )
}
