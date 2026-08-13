import { useState } from 'react'
import { ShieldCheckIcon } from 'lucide-react'
import DetectPage from '@/pages/DetectPage'

const TABS = [
  { id: 'detect', label: '检测' },
  { id: 'records', label: '记录' },
] as const

export default function App() {
  // 两个页签用 useState 切换即可，不引入路由库（YAGNI）
  const [tab, setTab] = useState<string>('detect')

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-[1400px] items-center gap-6 px-6">
          <div className="flex items-center gap-2 py-3.5">
            <ShieldCheckIcon className="size-[18px] text-primary" />
            <span className="font-medium tracking-tight">DocGuard 文档篡改审核台</span>
          </div>
          <nav className="flex self-stretch">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                /* 选中态用 2px 下边框 + 文字色，不用胶囊底色（禁令 3） */
                className={`-mb-px border-b-2 px-4 text-sm transition-colors ${
                  tab === t.id
                    ? 'border-primary text-foreground'
                    : 'border-transparent text-muted-foreground hover:text-foreground'
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {tab === 'detect' ? (
        <DetectPage />
      ) : (
        <div className="mx-auto max-w-[1400px] px-6 py-6 text-sm text-muted-foreground">
          检测记录（Task 9）
        </div>
      )}
    </div>
  )
}
