import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import { ShieldCheckIcon } from 'lucide-react'
import DetectPage from '@/pages/DetectPage'
import RunsPage from '@/pages/RunsPage'
import RunDetailPage from '@/pages/RunDetailPage'

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-background text-foreground">
        <header className="border-b border-border bg-card">
          <div className="mx-auto flex max-w-[1400px] items-center gap-6 px-6">
            <div className="flex items-center gap-2 py-3.5">
              <ShieldCheckIcon className="size-[18px] text-primary" />
              <span className="font-medium tracking-tight">DocGuard 文档篡改审核台</span>
            </div>
            <nav className="flex self-stretch">
              <Link
                to="/detect"
                className="-mb-px border-b-2 border-transparent px-4 text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                检测
              </Link>
              <Link
                to="/runs"
                className="-mb-px border-b-2 border-transparent px-4 text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                记录
              </Link>
            </nav>
          </div>
        </header>

        <main>
          <Routes>
            <Route path="/" element={<DetectPage />} />
            <Route path="/detect" element={<DetectPage />} />
            <Route path="/runs" element={<RunsPage />} />
            <Route path="/runs/:id" element={<RunDetailPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
