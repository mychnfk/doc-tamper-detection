import type { TraceEvent } from './types'

interface Handlers {
  onTrace: (e: TraceEvent) => void
  onDone: (d: { run_id: string; duration_ms: number }) => void
  onError: (msg: string) => void
}

/** EventSource 不支持 POST/multipart，故手工解析 SSE 帧。返回中止函数。 */
export function runDetection(file: File, mode: string, h: Handlers): () => void {
  const ctrl = new AbortController()
  const form = new FormData()
  form.append('file', file)
  form.append('mode', mode)

  ;(async () => {
    try {
      const resp = await fetch('/api/detect', { method: 'POST', body: form, signal: ctrl.signal })
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }))
        h.onError(body.detail ?? `HTTP ${resp.status}`)
        return
      }
      const reader = resp.body!.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const blocks = buf.split('\n\n')
        buf = blocks.pop() ?? ''      // 最后一段可能被截断，留到下一轮拼接
        for (const block of blocks) {
          let ev = '', data = ''
          for (const line of block.split('\n')) {
            if (line.startsWith('event: ')) ev = line.slice(7)
            else if (line.startsWith('data: ')) data = line.slice(6)
          }
          if (!ev || !data) continue
          const parsed = JSON.parse(data)
          if (ev === 'trace') h.onTrace(parsed)
          else if (ev === 'done') h.onDone(parsed)
          else if (ev === 'error') h.onError(parsed.message)
        }
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        // 这句文案不是客套：后端落盘先于推送，断连时已产生的事件确实躺在 runs/ 里
        h.onError('连接中断，已完成的部分可在「记录」页找回')
      }
    }
  })()

  return () => ctrl.abort()
}
