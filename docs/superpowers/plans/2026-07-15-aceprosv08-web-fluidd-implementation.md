# ACEPROSV08 Web and Fluidd Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish `Luomo520/fluidd-acepro-card-ACEPROSV08` with a safe Moonraker adapter, Chinese standalone UI, Fluidd v1.37.2 card, transactional installer, documentation, and real screenshots.

**Architecture:** ACEPROSV08 remains the hardware and G-code authority. A strict Moonraker component normalizes single-device status and exposes four stable endpoints; the standalone page and Fluidd card consume only those endpoints. The installer deploys Git-tracked assets through verified backups and atomic directory swaps.

**Tech Stack:** Python 3.11, Moonraker component APIs, Vue 2/Vuetify 2 for Fluidd v1.37.2, static Vue 3 page for `/ace.html`, Bash, pytest, Node test runner/Vitest, pnpm 11.10.0, Playwright browser verification, GitHub CLI.

---

## File Map

- `extras/ace.py`: ACEPROSV08 driver with three additional read-only status fields.
- `ace_status_integration/moonraker/ace_status.py`: status normalization, capability response, command validation, and endpoint handlers.
- `ace_status_integration/web/`: standalone Chinese web page and shared browser API client.
- `fluidd-source-overlay/`: Fluidd v1.37.2 source additions and narrow dashboard card.
- `fluidd-dist/`: reproducible Fluidd v1.37.2 build deployed to printers without Node.js.
- `scripts/build-fluidd.ps1`: apply the source overlay to the pinned Fluidd checkout and build `fluidd-dist`.
- `ui-installer.sh`: character menu, detection, transactional backup, install, update, health check, rollback, and uninstall.
- `tests/`: Python, JavaScript, installer, and contract tests.
- `docs/`: Chinese installation, usage, recovery, architecture, compatibility, and images.

### Task 1: Create the Target Repository Safely

**Files:**
- Create: `fluidd-acepro-card-ACEPROSV08/` from a fresh clone of `szkrisz/ACEPROSV08`
- Create: `fluidd-acepro-card-ACEPROSV08/docs/superpowers/specs/2026-07-15-aceprosv08-web-fluidd-design.md`
- Create: `fluidd-acepro-card-ACEPROSV08/docs/superpowers/plans/2026-07-15-aceprosv08-web-fluidd-implementation.md`
- Create: `fluidd-acepro-card-ACEPROSV08/.gitignore`

- [ ] **Step 1: Verify no target path or remote repository will be overwritten**

Run:

```powershell
Test-Path .\fluidd-acepro-card-ACEPROSV08
& .\.portable-tools\gh\bin\gh.exe repo view Luomo520/fluidd-acepro-card-ACEPROSV08 --json name,url 2>$null
```

Expected: local path is absent; if the GitHub repository exists, stop and inspect instead of recreating it.

- [ ] **Step 2: Clone the upstream baseline and create the feature branch**

```powershell
& .\.portable-tools\mingit\cmd\git.exe clone https://github.com/szkrisz/ACEPROSV08.git fluidd-acepro-card-ACEPROSV08
& .\.portable-tools\mingit\cmd\git.exe -C fluidd-acepro-card-ACEPROSV08 switch -c feat/web-fluidd-integration
```

Expected: HEAD equals upstream baseline `0311eb3` or a reviewed newer compatible commit.

- [ ] **Step 3: Add repository ignores and approved design documents**

`.gitignore` must contain:

```gitignore
.venv/
node_modules/
.pytest_cache/
__pycache__/
*.pyc
.build/
.superpowers/
test-results/
```

- [ ] **Step 4: Commit the project baseline**

```powershell
git add .gitignore docs/superpowers
git commit -m "docs: add ACEPROSV08 UI design and implementation plan"
```

### Task 2: Export Minimal Driver Status

**Files:**
- Modify: `extras/ace.py`
- Create: `tests/test_driver_status.py`

- [ ] **Step 1: Write the failing status export tests**

```python
def test_status_exports_connection_assist_and_dryer_limit(ace):
    ace._serial = object()
    ace._feed_assist_index = 2
    ace.max_dryer_temperature = 65
    status = ace.get_status()
    assert status["connected"] is True
    assert status["feed_assist_index"] == 2
    assert status["max_dryer_temperature"] == 65


def test_status_returns_independent_nested_objects(ace):
    first = ace.get_status()
    first["dryer"]["status"] = "changed"
    assert ace.get_status()["dryer"]["status"] != "changed"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_driver_status.py -q`

Expected: FAIL because the three fields are absent and the current shallow copy aliases nested dictionaries.

- [ ] **Step 3: Implement only the read-only export**

```python
import copy

def get_status(self, eventtime=None):
    status = copy.deepcopy(self._info)
    status["connected"] = self._serial is not None
    status["feed_assist_index"] = self._feed_assist_index
    status["max_dryer_temperature"] = self.max_dryer_temperature
    status["endless_spool"] = {
        "enabled": self.endless_spool_enabled,
        "runout_detected": self.endless_spool_runout_detected,
        "in_progress": self.endless_spool_in_progress,
    }
    return status
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_driver_status.py -q`

Expected: PASS.

Commit: `git add extras/ace.py tests/test_driver_status.py && git commit -m "feat: export ACE UI status fields"`

### Task 3: Implement the Moonraker API Contract

**Files:**
- Create: `ace_status_integration/moonraker/ace_status.py`
- Create: `tests/test_ace_status_component.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write failing normalization tests**

```python
def test_normalize_status_merges_inventory_and_sensors(component):
    result = component.normalize_status(
        ace={"connected": True, "status": "ready", "temp": 42.6,
             "feed_assist_index": -1, "max_dryer_temperature": 65,
             "dryer": {"status": "stop"}, "endless_spool": {"enabled": False}},
        variables={"ace_current_index": 0, "ace_inventory": [
            {"status": "ready", "color": [226, 58, 67], "material": "PLA", "temp": 210}
        ]},
        upper={"filament_detected": True}, lower={"filament_detected": False},
        printing=False,
    )
    assert result["connected"] is True
    assert result["current_tool"] == 0
    assert result["sensors"]["upper"]["detected"] is True
    assert result["sensors"]["lower"]["detected"] is False
```

- [ ] **Step 2: Write failing command validation tests**

```python
@pytest.mark.parametrize("payload", [
    {"command": "M112", "params": {}},
    {"command": "ACE_SET_SLOT", "params": {"INDEX": 4, "EMPTY": 1}},
    {"command": "ACE_FEED", "params": {"INDEX": 0, "LENGTH": 501, "SPEED": 20}},
    {"command": "ACE_SET_SLOT", "params": {"INDEX": 0, "COLOR": [1, 2, 3], "MATERIAL": "PLA\nM112", "TEMP": 210}},
])
def test_rejects_unsafe_commands(component, payload):
    with pytest.raises(AceRequestError):
        component.build_gcode(payload, printing=False, connected=True)


def test_builds_sv08_inventory_command_with_index(component):
    payload = {"command": "ACE_SET_SLOT", "params": {
        "INDEX": 1, "COLOR": [1, 2, 3], "MATERIAL": "PETG", "TEMP": 240}}
    assert component.build_gcode(payload, printing=False, connected=True) == (
        "ACE_SET_SLOT INDEX=1 COLOR=1,2,3 MATERIAL=PETG TEMP=240")
```

- [ ] **Step 3: Run tests and verify RED**

Run: `python -m pytest tests/test_ace_status_component.py -q`

Expected: FAIL because the component does not exist.

- [ ] **Step 4: Implement schemas, object queries, four handlers, and strict command builders**

Use one builder per command and a fixed dispatch table:

```python
COMMAND_BUILDERS = {
    "ACE_SET_SLOT": _build_set_slot,
    "ACE_CHANGE_TOOL": _build_change_tool,
    "ACE_CHANGE_SPOOL": _build_index_only,
    "ACE_FEED": _build_move,
    "ACE_RETRACT": _build_move,
    "ACE_ENABLE_FEED_ASSIST": _build_index_only,
    "ACE_DISABLE_FEED_ASSIST": _build_index_only,
    "ACE_START_DRYING": _build_drying,
    "ACE_STOP_DRYING": _build_without_params,
    "ACE_ENABLE_ENDLESS_SPOOL": _build_without_params,
    "ACE_DISABLE_ENDLESS_SPOOL": _build_without_params,
    "ACE_SAVE_INVENTORY": _build_without_params,
    "ACE_QUERY_SLOTS": _build_without_params,
}
```

Register `/server/ace/status`, `/server/ace/slots`, `/server/ace/capabilities`, and `/server/ace/command`. Raise Moonraker errors with 400, 409, and 503 status codes according to the design.

- [ ] **Step 5: Run the full Python suite and commit**

Run: `python -m pytest tests -q`

Expected: all Python tests PASS.

Commit: `git add ace_status_integration/moonraker tests && git commit -m "feat: add strict Moonraker ACE API"`

### Task 4: Build the Shared Browser API Client

**Files:**
- Create: `ace_status_integration/web/ace-client.mjs`
- Create: `tests/web/ace-client.test.mjs`

- [ ] **Step 1: Write failing client tests with Node's built-in test runner**

```javascript
import test from 'node:test'
import assert from 'node:assert/strict'
import { AceClient, normalizeHex } from '../../ace_status_integration/web/ace-client.mjs'

test('normalizes RGB into uppercase hex', () => {
  assert.equal(normalizeHex([226, 58, 67]), '#E23A43')
})

test('sends structured command JSON', async () => {
  const calls = []
  const client = new AceClient('', async (url, options) => {
    calls.push({ url, options })
    return { ok: true, json: async () => ({ success: true }) }
  })
  await client.command('ACE_CHANGE_TOOL', { TOOL: 2 })
  assert.equal(calls[0].url, '/server/ace/command')
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    command: 'ACE_CHANGE_TOOL', params: { TOOL: 2 }
  })
})
```

- [ ] **Step 2: Run and verify RED**

Run: `node --test tests/web/ace-client.test.mjs`

Expected: FAIL because `ace-client.mjs` is missing.

- [ ] **Step 3: Implement status, slots, capabilities, command, timeout, and Chinese error mapping**

The public API is exactly:

```javascript
export class AceClient {
  status() {}
  slots() {}
  capabilities() {}
  command(command, params = {}) {}
}
export function normalizeHex(rgb) {}
export function errorMessage(error) {}
```

- [ ] **Step 4: Run tests and commit**

Run: `node --test tests/web/ace-client.test.mjs`

Expected: PASS.

Commit: `git add ace_status_integration/web/ace-client.mjs tests/web/ace-client.test.mjs && git commit -m "feat: add shared ACE browser client"`

### Task 5: Implement the Chinese Standalone Page

**Files:**
- Create: `ace_status_integration/web/ace.html`
- Create: `ace_status_integration/web/ace-dashboard.css`
- Create: `ace_status_integration/web/ace-dashboard.js`
- Copy with attribution: `ace_status_integration/web/vue.global.prod.js`
- Create: `tests/web/standalone-page.test.mjs`

- [ ] **Step 1: Write a failing static contract test**

```javascript
test('standalone page exposes every required control', async () => {
  const html = await readFile('ace_status_integration/web/ace.html', 'utf8')
  for (const id of ['ace-status', 'upper-sensor', 'lower-sensor', 'dryer-controls',
    'slot-0', 'slot-1', 'slot-2', 'slot-3', 'endless-spool', 'manual-feed',
    'manual-retract', 'diagnostics']) assert.match(html, new RegExp(`id="${id}"`))
})
```

- [ ] **Step 2: Run and verify RED**

Run: `node --test tests/web/standalone-page.test.mjs`

Expected: FAIL because the page is missing.

- [ ] **Step 3: Implement the page using the approved Kobra-style spool geometry**

Each spool must use:

```html
<svg viewBox="0 0 200 140" class="spool-svg">
  <ellipse cx="60" cy="70" rx="36" ry="64" class="spool-flange-back" />
  <rect x="58" y="18" width="90" height="104" rx="40" ry="40"
        :fill="slot.color.hex" class="spool-body" />
  <ellipse cx="142" cy="70" rx="36" ry="64" class="spool-flange-front" />
  <ellipse cx="142" cy="70" rx="10" ry="20" class="spool-hole" />
</svg>
```

Keep form drafts separate from polling state; refresh slots only after successful saves.

- [ ] **Step 4: Run static tests and browser mock-state checks**

Run: `node --test tests/web/*.test.mjs`

Expected: PASS.

Commit: `git add ace_status_integration/web tests/web && git commit -m "feat: add Chinese standalone ACE dashboard"`

### Task 6: Port the Full Feature Set into Fluidd v1.37.2

**Files:**
- Create: `fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue`
- Create: `fluidd-source-overlay/src/components/widgets/acepro/AceProSlotCard.vue`
- Create: `fluidd-source-overlay/src/mixins/acePro.ts`
- Create: `fluidd-source-overlay/src/util/acepro.ts`
- Create: `fluidd-source-overlay/src/types/acepro.d.ts`
- Modify through overlay: Fluidd dashboard registration, router, navigation, store support detection, and layout defaults
- Create: `fluidd-source-overlay/src/util/acepro.test.ts`

- [ ] **Step 1: Write failing utility tests for the SV08 schema**

```typescript
it('builds ACE_SET_SLOT with INDEX and never T', () => {
  expect(buildSetSlotPayload(2, 'PLA', '#E23A43', 210)).toEqual({
    command: 'ACE_SET_SLOT',
    params: { INDEX: 2, MATERIAL: 'PLA', COLOR: [226, 58, 67], TEMP: 210 }
  })
})

it('preserves a dirty editor while polling', () => {
  expect(mergeSlotDraft(serverSlot, dirtyDraft, true)).toEqual(dirtyDraft)
})
```

- [ ] **Step 2: Apply the test overlay to a clean Fluidd v1.37.2 checkout and verify RED**

Run: `pnpm test:unit -- src/util/acepro.test.ts`

Expected: FAIL because utilities are missing.

- [ ] **Step 3: Implement API-backed mixin and components**

The desktop slot grid contract is:

```css
.acepro-slot-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:4px; }
@media (max-width:680px) { .acepro-slot-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:380px) { .acepro-slot-grid { grid-template-columns:1fr; } }
```

All commands call `/server/ace/command`; remove direct `sendGcode` and all `ACE_SET_SLOT T=` code.

- [ ] **Step 4: Run Fluidd unit tests, type check, lint, and build**

```powershell
pnpm test:unit -- src/util/acepro.test.ts
pnpm type-check
pnpm lint
pnpm build
```

Expected: all commands succeed without warnings introduced by ACE files.

- [ ] **Step 5: Commit the source overlay**

Commit: `git add fluidd-source-overlay && git commit -m "feat: add compact ACEPROSV08 Fluidd card"`

### Task 7: Produce a Reproducible Fluidd Build

**Files:**
- Create: `scripts/build-fluidd.ps1`
- Create: `fluidd-upstream.json`
- Create: `fluidd-dist/`
- Create: `manifest.sha256`

- [ ] **Step 1: Write a failing build manifest check**

```powershell
if (-not (Test-Path fluidd-dist\index.html)) { throw 'fluidd-dist/index.html missing' }
if (-not (Select-String fluidd-dist\index.html -Pattern 'ACEPROSV08_UI_VERSION' -Quiet)) {
  throw 'ACE UI marker missing'
}
```

- [ ] **Step 2: Implement the build script**

The script must verify Fluidd version `1.37.2`, copy to `.build/fluidd`, apply the overlay, run
`pnpm install --frozen-lockfile`, tests, type check, and build, then replace `fluidd-dist` only after success.

- [ ] **Step 3: Run build and checksum generation**

Run: `powershell -ExecutionPolicy Bypass -File scripts/build-fluidd.ps1`

Expected: `fluidd-dist/index.html` exists and `manifest.sha256` verifies every distributed file.

- [ ] **Step 4: Commit source and generated distribution together**

Commit: `git add scripts/build-fluidd.ps1 fluidd-upstream.json fluidd-dist manifest.sha256 && git commit -m "build: add verified Fluidd 1.37.2 distribution"`

### Task 8: Implement the Transactional Character Installer

**Files:**
- Create: `ui-installer.sh`
- Create: `uninstall.sh`
- Create: `tests/installer/test-installer.sh`

- [ ] **Step 1: Write failing fake-HOME installer tests**

```bash
test_force_install_still_requires_backup() {
  setup_fake_home
  ACEPRO_TEST_FAIL_BACKUP=1 run_installer --install-force
  assert_failure
  assert_not_exists "$FAKE_HOME/fluidd/.fluidd-aceprosv08-installed"
}

test_uninstall_restores_first_install_baseline() {
  setup_fake_home
  run_installer --install-force
  run_installer --uninstall --yes
  assert_file_contains "$FAKE_HOME/fluidd/index.html" "original-fluidd"
}
```

- [ ] **Step 2: Run with Git Bash and verify RED**

Run: `bash tests/installer/test-installer.sh`

Expected: FAIL because the installer is missing.

- [ ] **Step 3: Implement menu and noninteractive commands**

Supported commands:

```text
--install
--install-force
--uninstall
--status
--yes
```

The transaction order is fixed: lock, detect, enumerate targets, create timestamped backup, write
manifest, verify SHA-256, stage, validate, atomic swap, restart confirmation, health check, rollback on
failure. `--install-force` skips only driver/API detection.

- [ ] **Step 4: Run all installer scenarios**

Run: `bash tests/installer/test-installer.sh`

Expected: PASS for normal, force, backup failure, update, rollback, conflict, and uninstall cases.

- [ ] **Step 5: Commit**

Commit: `git add ui-installer.sh uninstall.sh tests/installer && git commit -m "feat: add transactional UI installer"`

### Task 9: Write Chinese Documentation and License Notices

**Files:**
- Modify: `README.md`
- Create: `docs/INSTALL.zh-CN.md`
- Create: `docs/USER_GUIDE.zh-CN.md`
- Create: `docs/RECOVERY.zh-CN.md`
- Create: `docs/ARCHITECTURE.zh-CN.md`
- Create: `THIRD_PARTY_NOTICES.md`
- Create: `CHANGELOG.md`
- Create: `VERSION`

- [ ] **Step 1: Write a failing documentation contract test**

```python
def test_readme_declares_exact_compatibility_and_commands():
    text = Path("README.md").read_text(encoding="utf-8")
    for required in ["szkrisz/ACEPROSV08", "不兼容 Kobra-S1/ACEPRO",
                     "Fluidd v1.37.2", "--install-force", "GPL-3.0"]:
        assert required in text
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_docs.py -q`

Expected: FAIL until the documentation is complete.

- [ ] **Step 3: Write complete tutorials and attribution**

README opening block must state:

```markdown
> 本项目仅适配 `szkrisz/ACEPROSV08` 驱动的单 ACE Pro、四料槽配置。
> 不兼容 `Kobra-S1/ACEPRO`，请勿混合安装。
```

Document Git clone installation, force-install risk, update with `git pull --ff-only`, backup location,
uninstall recovery, manual install, API troubleshooting, Fluidd update recovery, and GPL obligations.

- [ ] **Step 4: Run documentation tests and commit**

Run: `python -m pytest tests/test_docs.py -q`

Expected: PASS.

Commit: `git add README.md docs THIRD_PARTY_NOTICES.md CHANGELOG.md VERSION tests/test_docs.py && git commit -m "docs: add Chinese install and usage guides"`

### Task 10: Verify Visuals and Add Real Images

**Files:**
- Create: `tests/visual/mock-ace-api.js`
- Create: `docs/images/fluidd-acepro-card.png`
- Create: `docs/images/acepro-standalone.png`
- Modify: `README.md`

- [ ] **Step 1: Start the built Fluidd with deterministic mock API data**

Run: `pnpm exec vite preview --host 127.0.0.1 --port 4173`

Expected: built Fluidd opens with connected T0, four slots, two active sensors, and stopped dryer.

- [ ] **Step 2: Verify layout by browser measurements**

At 1366px Fluidd layout assert:

```javascript
expect(Math.round(card.width)).toBeGreaterThanOrEqual(620)
expect(Math.round(card.width)).toBeLessThanOrEqual(640)
expect(new Set(slots.map(slot => Math.round(slot.y))).size).toBe(1)
expect(slots.every(slot => slot.scrollWidth <= slot.clientWidth)).toBe(true)
```

Repeat at 1920px, tablet, and phone; desktop is four across, mobile is 2x2, narrow mobile is one column.

- [ ] **Step 3: Capture privacy-safe screenshots from the actual build**

Crop the actual card to `docs/images/fluidd-acepro-card.png` and the standalone page to
`docs/images/acepro-standalone.png`. Ensure no IP, username, local path, token, or printer identity appears.

- [ ] **Step 4: Embed images and commit**

```markdown
![ACE Pro Fluidd 卡片](docs/images/fluidd-acepro-card.png)
![ACE Pro 独立控制界面](docs/images/acepro-standalone.png)
```

Commit: `git add README.md docs/images tests/visual && git commit -m "docs: add verified ACE interface screenshots"`

### Task 11: Final Verification and GitHub Publication

**Files:**
- Modify only if verification finds a tested defect

- [ ] **Step 1: Run complete verification**

```powershell
python -m pytest tests -q
node --test tests/web/*.test.mjs
bash tests/installer/test-installer.sh
pnpm test:unit
pnpm type-check
pnpm lint
pnpm build
```

Expected: all tests and builds PASS; `git status --short` contains only intended tracked changes.

- [ ] **Step 2: Audit secrets, private data, license, and generated checksums**

Run searches for `192.168.`, passwords, usernames, absolute Windows paths, private keys, tokens, and
unattributed copied files. Verify `manifest.sha256` and `THIRD_PARTY_NOTICES.md`.

- [ ] **Step 3: Create or reuse the GitHub repository without overwriting anything**

Use GitHub CLI to create `Luomo520/fluidd-acepro-card-ACEPROSV08` as public only if it does not exist,
set `origin`, and preserve `upstream` as `szkrisz/ACEPROSV08`.

- [ ] **Step 4: Push the feature branch and open a reviewable pull request or merge after verification**

```powershell
git push -u origin feat/web-fluidd-integration
gh pr create --title "feat: add ACEPROSV08 web and Fluidd integration" --body-file .github/PR_BODY.md
```

- [ ] **Step 5: Publish v0.1.0 only after the default branch contains the verified commit**

Release notes must list exact driver compatibility, Fluidd v1.37.2, single-device limitation, install and
rollback commands, GPL-3.0 attribution, checksums, and both screenshots. Installation remains Git-based;
do not attach an installer archive.
