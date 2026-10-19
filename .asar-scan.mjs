import fs from 'node:fs'
const ASAR = 'D:/deepseek/resources/app.asar'
const fd = fs.openSync(ASAR, 'r')
const head = Buffer.alloc(20)
fs.readSync(fd, head, 0, 20, 0)
const headerSize = head.readUInt32LE(4)
const jsonSize = head.readUInt32LE(12)
const hb = Buffer.alloc(jsonSize)
fs.readSync(fd, hb, 0, jsonSize, 16)
const header = JSON.parse(hb.toString('utf8'))
const base = 8 + headerSize
function walk(cur, prefix, out) {
  for (const [name, child] of Object.entries(cur.files ?? {})) {
    const full = prefix ? `${prefix}/${name}` : name
    if (child.files) walk(child, full, out)
    else if (child.link === undefined) out.push([full, child.size, Number(child.offset)])
  }
  return out
}
const [needle, prefix = '', max = '6'] = process.argv.slice(2)
const files = walk(header, '', [])
let hits = 0
for (const [f, size, off] of files) {
  if (!f.includes(prefix) || size > Number(max) * 1024 * 1024) continue
  if (!/\.(js|mjs|cjs)$/.test(f)) continue
  const b = Buffer.alloc(size)
  fs.readSync(fd, b, 0, size, base + off)
  let i = b.indexOf(needle)
  if (i === -1) continue
  hits++
  // print every occurrence's line, up to 3 per file
  let n = 0
  while (i !== -1 && n < 3) {
    const start = Math.max(0, b.lastIndexOf(10, Math.max(0, i - 600)))
    const end = b.indexOf(10, i + 400)
    const block = b.subarray(start, end === -1 ? size : end).toString('utf8').split('\n').filter(Boolean)
    console.log(`${f}`)
    for (const line of block.slice(-14)) console.log(`    ${line.trim().slice(0, 240)}`)
    i = b.indexOf(needle, i + 1)
    n++
  }
  if (hits > 10) break
}
console.log('files scanned:', files.length, 'hits:', hits)
