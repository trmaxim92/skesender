<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

type Node = {
  x: number
  y: number
  z: number
  vx: number
  vy: number
  vz: number
}

const canvasRef = ref<HTMLCanvasElement | null>(null)

let raf = 0
let nodes: Node[] = []
let w = 0
let h = 0
let dpr = 1
let reduceMotion = false
let onResize: (() => void) | null = null

const LINK_DIST = 140
const NODE_COUNT_BASE = 70

function spawn(): Node {
  return {
    x: Math.random() * w,
    y: Math.random() * h,
    z: 0.35 + Math.random() * 0.9,
    vx: (Math.random() - 0.5) * 0.35,
    vy: (Math.random() - 0.5) * 0.35,
    vz: (Math.random() - 0.5) * 0.002,
  }
}

function resize(canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D) {
  dpr = Math.min(window.devicePixelRatio || 1, 2)
  w = window.innerWidth
  h = window.innerHeight
  canvas.width = Math.floor(w * dpr)
  canvas.height = Math.floor(h * dpr)
  canvas.style.width = `${w}px`
  canvas.style.height = `${h}px`
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

  const count = Math.round(
    NODE_COUNT_BASE * Math.min(1.4, Math.max(0.7, (w * h) / (1280 * 720))),
  )
  if (nodes.length !== count) {
    nodes = Array.from({ length: count }, () => spawn())
  }
}

function step(ctx: CanvasRenderingContext2D) {
  ctx.clearRect(0, 0, w, h)

  const g = ctx.createRadialGradient(
    w * 0.5,
    h * 0.45,
    0,
    w * 0.5,
    h * 0.5,
    Math.max(w, h) * 0.7,
  )
  g.addColorStop(0, 'rgba(8, 40, 72, 0.35)')
  g.addColorStop(1, 'rgba(1, 6, 18, 0)')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, w, h)

  if (!reduceMotion) {
    for (const n of nodes) {
      n.x += n.vx * n.z
      n.y += n.vy * n.z
      n.z += n.vz
      if (n.z < 0.3 || n.z > 1.35) n.vz *= -1
      if (n.x < -40 || n.x > w + 40) n.vx *= -1
      if (n.y < -40 || n.y > h + 40) n.vy *= -1
      n.x = Math.min(w + 40, Math.max(-40, n.x))
      n.y = Math.min(h + 40, Math.max(-40, n.y))
    }
  }

  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i]!
    for (let j = i + 1; j < nodes.length; j++) {
      const b = nodes[j]!
      const dx = a.x - b.x
      const dy = a.y - b.y
      const dist = Math.hypot(dx, dy)
      const maxDist = LINK_DIST * ((a.z + b.z) * 0.55)
      if (dist > maxDist) continue
      const alpha = (1 - dist / maxDist) * Math.min(a.z, b.z) * 0.55
      ctx.beginPath()
      ctx.moveTo(a.x, a.y)
      ctx.lineTo(b.x, b.y)
      ctx.strokeStyle = `rgba(80, 220, 255, ${alpha})`
      ctx.lineWidth = 0.7 * Math.min(a.z, b.z)
      ctx.stroke()
    }
  }

  const ordered = [...nodes].sort((a, b) => a.z - b.z)
  for (const n of ordered) {
    const r = 1.2 + n.z * 2.8
    const blur = (1.2 - Math.min(n.z, 1.2)) * 6
    const alpha = 0.25 + n.z * 0.65

    ctx.save()
    if (blur > 0.4) ctx.filter = `blur(${blur}px)`
    ctx.beginPath()
    ctx.arc(n.x, n.y, r * 2.2, 0, Math.PI * 2)
    ctx.fillStyle = `rgba(56, 200, 255, ${alpha * 0.18})`
    ctx.fill()

    ctx.beginPath()
    ctx.arc(n.x, n.y, r, 0, Math.PI * 2)
    ctx.fillStyle = `rgba(170, 245, 255, ${alpha})`
    ctx.shadowColor = 'rgba(0, 210, 255, 0.9)'
    ctx.shadowBlur = 12 * n.z
    ctx.fill()
    ctx.restore()
  }

  raf = requestAnimationFrame(() => step(ctx))
}

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  onResize = () => resize(canvas, ctx)
  onResize()
  window.addEventListener('resize', onResize)
  raf = requestAnimationFrame(() => step(ctx))
})

onUnmounted(() => {
  cancelAnimationFrame(raf)
  if (onResize) window.removeEventListener('resize', onResize)
})
</script>

<template>
  <canvas
    ref="canvasRef"
    class="pointer-events-none absolute inset-0 h-full w-full"
    aria-hidden="true"
  />
</template>
