import { useState } from 'react'
import { ReactCompareSlider, ReactCompareSliderImage } from 'react-compare-slider'

/**
 * 原图 ⇄ 热力图对比。
 *
 * 容器宽高比跟随图片本身，而不是写死高度：两者都是 object-contain，
 * 固定高度会让接近正方形的单据在宽容器里两侧留出大片空底（实测浪费 35% 横向空间）。
 * 宽高比从原图 onLoad 读，拿到之前先用 4/3 占位避免布局跳动。
 */
export function CompareSlider({ original, heatmap }: { original: string; heatmap: string }) {
  const [ratio, setRatio] = useState(4 / 3)

  return (
    <div className="overflow-hidden rounded-[var(--radius)] border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5 text-sm">
        <span className="font-medium">原图 ⇄ 篡改热力图</span>
        <span className="text-xs text-muted-foreground">拖动分割线对比</span>
      </div>
      <div className="mx-auto max-h-[62vh]" style={{ aspectRatio: ratio }}>
        <ReactCompareSlider
          className="size-full"
          itemOne={
            <ReactCompareSliderImage
              src={original}
              alt="原图"
              onLoad={(e) => {
                const el = e.currentTarget
                if (el.naturalHeight) setRatio(el.naturalWidth / el.naturalHeight)
              }}
            />
          }
          itemTwo={<ReactCompareSliderImage src={heatmap} alt="篡改热力图" />}
        />
      </div>
      <div className="flex items-center gap-4 border-t border-border px-4 py-2 text-xs text-muted-foreground">
        <span>左：原始单据</span>
        <span>右：TruFor 逐像素篡改概率（暖色为高）</span>
      </div>
    </div>
  )
}
