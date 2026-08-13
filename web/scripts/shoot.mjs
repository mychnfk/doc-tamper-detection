// scripts/shoot.mjs — 用系统 Chrome 跑一次真实检测并截图，供自审与 Task 11 三态核对
// 用法：node scripts/shoot.mjs <图片路径> <模式> <输出前缀>
import { chromium } from 'playwright'

const [img, mode = 'cv', out = '/tmp/dg'] = process.argv.slice(2)
const BASE = 'http://127.0.0.1:8000'

const browser = await chromium.launch({ channel: 'chrome' })
const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 2 })

const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
page.on('pageerror', (e) => errors.push(String(e)))

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.screenshot({ path: `${out}-1-empty.png`, fullPage: true })

await page.setInputFiles('input[type=file]', img)
// radio 是 sr-only、由 label 承载点击（键鼠都正常），所以点 label 而不是 .check()
const MODE_TEXT = { cv: '仅像素取证', direct: '快速复核', agent: 'Agent 复核' }
await page.locator('label', { hasText: MODE_TEXT[mode] }).last().click()
await page.screenshot({ path: `${out}-2-ready.png`, fullPage: true })

await page.getByRole('button', { name: '开始检测' }).click()
await page.waitForTimeout(1500)
await page.screenshot({ path: `${out}-3-running.png`, fullPage: true })

// 结论卡片出现即视为完成；agent 模式最长等 4 分钟
await page.waitForSelector('.dg-verdict', { timeout: 240_000 })
await page.waitForTimeout(600)
await page.screenshot({ path: `${out}-4-done.png`, fullPage: true })

// 展开两处折叠，核对渐进式披露第三层
const why = page.getByRole('button', { name: /为什么这么判/ })
if (await why.count()) { await why.click(); await page.waitForTimeout(200) }
await page.getByRole('button', { name: /技术细节/ }).click()
await page.waitForTimeout(400)
await page.screenshot({ path: `${out}-5-expanded.png`, fullPage: true })

console.log(errors.length ? `控制台报错 ${errors.length} 条:\n` + errors.join('\n') : '控制台无报错')
await browser.close()
