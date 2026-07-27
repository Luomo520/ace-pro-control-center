# ACE Pro Card More Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shorten the Fluidd dashboard ACE Pro card by placing calibration, manual feed, and quick actions behind one default-collapsed “更多功能” control while leaving the dedicated ACE page expanded.

**Architecture:** Add one explicit presentation prop and local expansion state to `AceProCard`; keep all existing controls mounted inside a Vuetify expand transition so their state and API behavior remain unchanged. The dashboard uses the prop default, while `AcePro.vue` explicitly disables the fold. Build from the synchronized Fluidd v1.37.2 checkout and replace the packaged distribution only after tests pass.

**Tech Stack:** Vue 2, TypeScript, Vuetify 2, Node test runner, Vitest, vue-tsc, ESLint, Vite, PowerShell deployment tooling.

---

### Task 1: Define the dashboard-only fold contract

**Files:**
- Modify: `tests/web/fluidd-card-layout.test.mjs`

- [ ] **Step 1: Write the failing contract test**

Add a test that reads `AceProCard.vue` and `AcePro.vue` and requires:

```js
test('dashboard folds advanced ACE controls behind more features', async () => {
  const [card, page] = await Promise.all([
    readFile('fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue', 'utf8'),
    readFile('fluidd-source-overlay/src/views/AcePro.vue', 'utf8'),
  ])

  assert.match(card, /readonly collapseExtraFunctions!:\s*boolean/)
  assert.match(card, /更多功能/)
  assert.match(card, /:aria-expanded="showExtraFunctions"/)
  assert.match(card, /<v-expand-transition>[\s\S]*v-show="showExtraFunctions"[\s\S]*acepro-panel--calibration[\s\S]*acepro-panel--manual[\s\S]*acepro-panel--quick[\s\S]*<\/v-expand-transition>/)
  assert.match(page, /:collapse-extra-functions="false"/)
})
```

- [ ] **Step 2: Run the test and verify RED**

Run: `node --test tests/web/fluidd-card-layout.test.mjs`

Expected: one failure because the fold prop and “更多功能” markup do not exist.

### Task 2: Implement the fold without changing control behavior

**Files:**
- Modify: `fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue`
- Modify: `fluidd-source-overlay/src/views/AcePro.vue`

- [ ] **Step 1: Add the presentation prop and local state**

Add to `AceProCard`:

```ts
@Prop({ type: Boolean, default: true })
readonly collapseExtraFunctions!: boolean

extraFunctionsOpen = false

get showExtraFunctions (): boolean {
  return !this.collapseExtraFunctions || this.extraFunctionsOpen
}
```

- [ ] **Step 2: Add the accessible toggle and one shared transition**

After the slot panel, render a real button only when folding is enabled:

```vue
<button
  v-if="collapseExtraFunctions"
  type="button"
  class="acepro-more-toggle"
  :aria-expanded="showExtraFunctions"
  @click="extraFunctionsOpen = !extraFunctionsOpen"
>
  <span>更多功能</span>
  <v-icon small>{{ showExtraFunctions ? '$chevronUp' : '$chevronDown' }}</v-icon>
</button>
```

Insert `<v-expand-transition><div v-show="showExtraFunctions" class="acepro-extra-functions">`
immediately before `<section class="acepro-panel acepro-panel--calibration">`. Insert the matching
`</div></v-expand-transition>` immediately after the closing `</section>` of
`<section class="acepro-panel acepro-panel--quick">`. Do not edit any markup inside those three
sections.

Style `.acepro-more-toggle` as a full-width compact Fluidd panel row with a visible focus ring, and remove the last child panel margin inside `.acepro-extra-functions`.

- [ ] **Step 3: Keep the dedicated page expanded**

Change `AcePro.vue` to:

```vue
<ace-pro-card
  :show-page-link="false"
  :collapse-extra-functions="false"
/>
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `node --test tests/web/fluidd-card-layout.test.mjs`

Expected: all tests pass.

- [ ] **Step 5: Commit the source behavior**

```bash
git add tests/web/fluidd-card-layout.test.mjs fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue fluidd-source-overlay/src/views/AcePro.vue
git commit -m "feat: fold ACE dashboard advanced controls"
```

### Task 3: Synchronize and verify Fluidd

**Files:**
- Modify: `../fluidd-develop/src/components/widgets/acepro/AceProCard.vue`
- Modify: `../fluidd-develop/src/views/AcePro.vue`

- [ ] **Step 1: Copy the two reviewed Overlay files to the matching Fluidd source paths**

Use `Copy-Item -LiteralPath` for only the two files, then compare SHA-256 values and require equality.

- [ ] **Step 2: Run frontend verification**

Run in `../fluidd-develop`:

```powershell
pnpm.cmd type-check
pnpm.cmd lint
pnpm.cmd test:unit --run
pnpm.cmd build
```

Expected: type check, lint, all unit tests, and production build exit `0`.

### Task 4: Replace and verify the packaged Fluidd build

**Files:**
- Replace: `fluidd-dist/**`
- Modify: `manifest.sha256`

- [ ] **Step 1: Preserve the old local distribution**

Move the current `fluidd-dist` to a timestamped directory under `.temporary/`; do not delete or overwrite earlier backups.

- [ ] **Step 2: Copy the clean `../fluidd-develop/dist` tree into `fluidd-dist`**

Require `index.html`, all referenced JS/CSS assets, and exactly one current ACE view/card asset set.

- [ ] **Step 3: Regenerate and verify `manifest.sha256`**

Enumerate tracked release files plus the complete `fluidd-dist` tree, excluding `.git`,
`.temporary`, `.playwright-cli`, caches, and local backup directories. For each file write a
lowercase SHA-256 line in GNU format:

```powershell
"$($hash.ToLowerInvariant()) *$($relativePath.Replace('\\', '/'))"
```

Save using UTF-8 without BOM and LF line endings. Parse every generated line, recompute each hash,
and require zero missing or mismatched files before installation.

- [ ] **Step 4: Run repository regression tests**

```powershell
node --test tests/web/*.test.mjs
& "C:\Users\Luomo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s tests -p "test_*.py" -v
```

Expected: Web and Python suites pass with zero failures.

- [ ] **Step 5: Commit the build payload**

```bash
git add fluidd-dist manifest.sha256
git commit -m "build: package ACE dashboard fold"
```

### Task 5: Visual and live deployment verification

**Files:**
- Remote: `/home/luomo/fluidd/**`
- Local backup tool: `../printer-tools/Backup-PrinterConfig.ps1`

- [ ] **Step 1: Preview desktop and narrow layouts**

Open the rebuilt Fluidd against the printer API. Verify the dashboard is collapsed by default, “更多功能” expands all three sections, the dedicated `#/acepro` page remains expanded, and no control overlaps at desktop or 390 px width.

- [ ] **Step 2: Confirm printer idle and create the mandatory before-change backup**

Query `print_stats`; stop if state is `printing` or `paused`. Run `Backup-PrinterConfig.ps1` with a detailed reason describing the Fluidd-only deployment.

- [ ] **Step 3: Deploy through the transactional installer**

Upload the verified tracked worktree to a timestamped staging directory, verify its archive SHA-256 and `manifest.sha256`, then run `ui-installer.sh --yes --install-card`. Preserve the installer `old/` archive and current Fluidd `config.json`.

- [ ] **Step 4: Restart Moonraker only if required and verify live UI**

Recheck `print_stats` before restart. Validate Fluidd, `/ace.html`, ACE API and browser rendering. Do not execute any physical ACE command.

- [ ] **Step 5: Create and verify the mandatory after-change backup**

Run `Backup-PrinterConfig.ps1` with a detailed after-change reason. Verify both backup directories, their descriptions, manifests and SHA-256 files, then report the installer rollback archive.
