<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

type Pt = { x: number; y: number; vx: number; vy: number }

const canvasRef = ref<HTMLCanvasElement | null>(null)

let raf = 0
let pts: Pt[] = []
let w = 0
let h = 0
let dpr = 1
let reduceMotion = false
let running = true
let lastTs = 0
let onResize: (() => void) | null = null
let onVis: (() => void) | null = null

const LINK = 110
const TARGET_FPS = 30
const FRAME_MS = 1000 / TARGET_FPS

function countForViewport() {
  const area = w * h
  if (area < 500_000) return 28
  if (area < 1_200_000) return 36
  return 42
}

function spawn(): Pt {
  return {
    x: Math.random() * w,
    y: Math.random() * h,
    vx: (Math.random() - 0.5) * 0.28,
    vy: (Math.random() - 0.5) * 0.28,
  }
}

function resize(canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D) {
  dpr = Math.min(window.devicePixelRatio || 1, 1.5)
  w = window.innerWidth
  h = window.innerHeight
  canvas.width = Math.floor(w * dpr)
  canvas.height = Math.floor(h * dpr)
  canvas.style.width = `${w}px`
  canvas.style.height = `${h}px`
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

  const n = countForViewport()
  if (pts.length !== n) pts = Array.from({ length: n }, () => spawn())
}

function step(ctx: CanvasRenderingContext2D, ts: number) {
  raf = requestAnimationFrame((t) => step(ctx, t))
  if (!running) return
  if (ts - lastTs < FRAME_MS) return
  lastTs = ts

  ctx.clearRect(0, 0, w, h)

  if (!reduceMotion) {
    for (const p of pts) {
      p.x += p.vx
      p.y += p.vy
      if (p.x < 0 || p.x > w) p.vx *= -1
      if (p.y < 0 || p.y > h) p.vy *= -1
      p.x = Math.min(w, Math.max(0, p.x))
      p.y = Math.min(h, Math.max(0, p.y))
    }
  }

  const link2 = LINK * LINK
  ctx.lineWidth = 1
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i]!
    for (let j = i + 1; j < pts.length; j++) {
      const b = pts[j]!
      const dx = a.x - b.x
      const dy = a.y - b.y
      const d2 = dx * dx + dy * dy
      if (d2 > link2) continue
      const alpha = (1 - Math.sqrt(d2) / LINK) * 0.35
      ctx.strokeStyle = `rgba(161, 13, 33, ${alpha})`
      ctx.beginPath()
      ctx.moveTo(a.x, a.y)
      ctx.lineTo(b.x, b.y)
      ctx.stroke()
    }
  }

  for (const p of pts) {
    ctx.beginPath()
    ctx.arc(p.x, p.y, 1.8, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(161, 13, 33, 0.45)'
    ctx.fill()
  }
}

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d', { alpha: true })
  if (!ctx) return

  reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  onResize = () => resize(canvas, ctx)
  onResize()
  window.addEventListener('resize', onResize, { passive: true })

  onVis = () => {
    running = document.visibilityState === 'visible'
    if (running) lastTs = 0
  }
  document.addEventListener('visibilitychange', onVis)

  raf = requestAnimationFrame((t) => step(ctx, t))
})

onUnmounted(() => {
  cancelAnimationFrame(raf)
  if (onResize) window.removeEventListener('resize', onResize)
  if (onVis) document.removeEventListener('visibilitychange', onVis)
})
</script>

<template>
  <canvas
    ref="canvasRef"
    class="pointer-events-none absolute inset-0 h-full w-full"
    aria-hidden="true"
  />
</template>
