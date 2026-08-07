import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const project = path.resolve(here, '../..')
const frontendFiles = [
  'frontend/dashboard/app.js',
  'frontend/fluidd-overlay/src/components/widgets/ace-v3/AceV3Card.vue',
  'frontend/simulator/app.js',
]

function extractFunction (source, name) {
  const start = source.indexOf(`function ${name} (`)
  assert.notEqual(start, -1, `${name} must be declared as a function`)
  const bodyStart = source.indexOf('{', start)
  let depth = 0
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1
    if (source[index] === '}') depth -= 1
    if (depth === 0) return source.slice(start, index + 1)
  }
  assert.fail(`${name} has no closing brace`)
}

function loadCollector (source) {
  const declaration = extractFunction(source, 'collectToolchangeNotices')
  return Function(`"use strict"; ${declaration}; return collectToolchangeNotices`)()
}

const notice = (sequence, command = `T${sequence}`, message = `notice-${sequence}`) => ({
  sequence,
  code: 'TOOLCHANGE_NOT_READY',
  command,
  message,
})

function advance (collector, tracker, notices) {
  const batch = collector(notices, tracker.cursor, tracker.cursorSignature)
  tracker.cursor = batch.cursor
  tracker.cursorSignature = batch.cursorSignature
  return batch.notices.map(item => item.sequence)
}

test('all frontends deliver the initial notice queue and every notice after a sequence restart', async () => {
  for (const relative of frontendFiles) {
    const source = await readFile(path.join(project, relative), 'utf8')
    const collector = loadCollector(source)
    const tracker = { cursor: null, cursorSignature: '' }

    assert.deepEqual(advance(collector, tracker, [notice(10), notice(11), notice(12)]), [10, 11, 12], `${relative}: initial queue`)
    assert.deepEqual(advance(collector, tracker, [notice(10), notice(11), notice(12)]), [], `${relative}: repeated poll`)
    assert.deepEqual(advance(collector, tracker, [notice(11), notice(12), notice(13)]), [13], `${relative}: normal increment`)
    assert.deepEqual(advance(collector, tracker, [notice(1)]), [1], `${relative}: first notice after restart`)
    assert.deepEqual(advance(collector, tracker, [notice(1), notice(2)]), [2], `${relative}: later notice after restart`)
    assert.deepEqual(advance(collector, tracker, [notice(1), notice(2)]), [], `${relative}: restarted queue deduplication`)
  }
})

test('same sequence with new content starts a new notification epoch', async () => {
  for (const relative of frontendFiles) {
    const source = await readFile(path.join(project, relative), 'utf8')
    const collector = loadCollector(source)
    const tracker = { cursor: null, cursorSignature: '' }

    assert.deepEqual(advance(collector, tracker, [notice(1, 'T1', 'before restart')]), [1])
    assert.deepEqual(advance(collector, tracker, [notice(1, 'T1', 'after restart')]), [1], relative)
  }
})

test('Fluidd keeps notices in one snackbar queue without clearing pending entries', async () => {
  const source = await readFile(path.join(project, frontendFiles[1]), 'utf8')
  assert.match(source, /if \(this\.noticeSnackbar \|\| this\.activeNotice \|\| !this\.noticeQueue\.length\) return/)
  assert.match(source, /this\.noticeQueue\.push\(\.\.\.batch\.notices\)/)
  assert.match(source, /this\.activeNotice = this\.noticeQueue\.shift\(\)/)
  assert.match(source, /this\.\$nextTick\(\(\) => this\.showNextToolchangeNotice\(\)\)/)
  assert.doesNotMatch(source, /this\.noticeQueue\s*=\s*\[\]/)
})
