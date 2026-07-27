# ACE Pro Automatic Print Drying and Compact Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add driver-owned automatic print drying with material-safe temperature selection, expose identical controls and status in Fluidd and `/ace.html`, and correct the compact quick-action layout without risking active prints or existing user configuration.

**Architecture:** `extras/ace.py` is the single authority for material classification, print lifecycle, dryer ownership, retries, persistence, and notices. Moonraker only normalizes that state and validates two new no-parameter commands; Fluidd and `/ace.html` render the same backend result and never recalculate temperatures. The Fluidd v1.37.2 source checkout is the build workspace, while this repository stores the reviewed overlay and one clean generated `fluidd-dist` payload.

**Tech Stack:** Python 3.11 `unittest`, Klipper reactor and G-code APIs, Moonraker component APIs, Vue 2.7/Vuetify 2, TypeScript 6, Vitest 4, Vue 3 standalone page, pnpm 11.10.0, Bash installer tests, Playwright, PowerShell printer backup tooling.

---

## File Map

- `extras/ace.py`: automatic drying policy, state machine, persistent switch, ACE requests, notices, and exported status.
- `tests/test_ace_driver_auto_drying.py`: isolated driver policy and lifecycle tests with fake reactor, printer, G-code, and ACE transport.
- `ace_status_integration/moonraker/ace_status.py`: normalized `auto_drying` response and strict enable/disable command whitelist.
- `tests/test_ace_status_component.py`: Moonraker response and command contract tests.
- `fluidd-source-overlay/src/types/acePro.ts`: typed automatic drying state.
- `fluidd-source-overlay/src/util/acepro.ts`: normalization and display-label helpers only; no temperature policy.
- `fluidd-source-overlay/src/util/acepro.test.ts`: API/fallback normalization, labels, and notice behavior tests.
- `fluidd-source-overlay/src/mixins/acePro.ts`: polling, notice de-duplication, confirmation, and command dispatch.
- `fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue`: compact switch placement, dryer toggle, and top status display.
- `ace_status_integration/web/ace.html`: standalone toggle and status markup.
- `ace_status_integration/web/ace-dashboard.js`: standalone state ingestion, notice de-duplication, confirmation, and commands.
- `ace_status_integration/web/ace-dashboard.css`: compact automatic drying controls at desktop and narrow widths.
- `tests/web/auto-drying-page.test.mjs`: static standalone-page contract tests.
- `C:/Users/Luomo/Documents/ace profluidd上的可视化界面/fluidd-develop/`: Fluidd v1.37.2 working source used for tests and production build.
- `fluidd-dist/`: complete clean Fluidd build produced from the synchronized v1.37.2 source.
- `VERSION`, `CHANGELOG.md`, `README.md`, `docs/DRIVER-v1.1.0.zh-CN.md`: versioned user and driver documentation.
- `manifest.sha256`: regenerated payload checksums after all source and distribution changes.

### Task 1: Add the Material-Safe Temperature Policy

**Files:**
- Create: `tests/test_ace_driver_auto_drying.py`
- Modify: `extras/ace.py` near `ACEPROSV08_DRIVER_VERSION` and inventory initialization

- [ ] **Step 1: Write failing table-driven policy tests**

Create a serial-module stub like `tests/test_ace_driver_feed.py`, load `extras/ace.py`, and add:

```python
class AutoDryingPolicyTests(unittest.TestCase):
    def test_selects_material_safe_temperature(self):
        cases = [
            ([slot("PLA")], (45, "PLA_ONLY")),
            ([slot("PLA"), slot("ABS")], (50, "PLA_MIXED")),
            ([slot("PLA"), slot("PETG")], (50, "PLA_MIXED")),
            ([slot("ABS"), slot("ABSCF"), slot("PETG"), slot("PAHTCF")], (60, "HIGH_TEMP")),
            ([slot("PETCF"), slot("PEEK")], (60, "HIGH_TEMP")),
            ([slot("PLA"), slot("Mystery")], (45, "UNKNOWN")),
            ([slot("")], (45, "UNKNOWN")),
            ([], (0, "EMPTY")),
        ]
        for slots, expected in cases:
            with self.subTest(slots=slots):
                self.assertEqual(ace_driver.select_auto_drying_policy(slots), expected)

    def test_ignores_hardware_and_inventory_slots_that_are_both_empty(self):
        self.assertEqual(
            ace_driver.select_auto_drying_policy([
                {"status": "empty", "material": "ABS"},
                {"status": "ready", "material": "PLA"},
            ]),
            (45, "PLA_ONLY"),
        )
```

Use this complete helper in the test file:

```python
def slot(material, status="ready"):
    return {"status": status, "material": material}
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```powershell
python -m unittest tests.test_ace_driver_auto_drying.AutoDryingPolicyTests -v
```

Expected: `ERROR` because `select_auto_drying_policy` does not exist.

- [ ] **Step 3: Implement the pure policy and reason metadata**

Add these constants and pure function to `extras/ace.py`:

```python
AUTO_DRYING_DURATION_MINUTES = 1440
AUTO_DRYING_KNOWN_MATERIALS = {
    'PLA', 'ABS', 'ABSCF', 'PETG', 'PAHTCF', 'PETCF', 'PEEK'
}
AUTO_DRYING_MESSAGES = {
    'EMPTY': '未检测到可烘干耗材，本次打印不会自动启动烘干。',
    'UNKNOWN': '检测到未知材料，将以 45°C 进行自动烘干，部分材料的烘干效果可能受限。',
    'PLA_MIXED': '检测到 PLA 与其他材料混装，自动烘干使用 50°C 以保护 PLA；其他高温材料的烘干效果可能受限。',
    'PLA_ONLY': '自动烘干使用 45°C：全部已装载耗材均为 PLA。',
    'HIGH_TEMP': '自动烘干使用 60°C：已装载耗材均为高温材料。',
}

def select_auto_drying_policy(slots):
    loaded = []
    for slot_data in slots:
        status = str(slot_data.get('status') or 'empty').strip().lower()
        if status == 'empty':
            continue
        loaded.append(str(slot_data.get('material') or '').strip().upper())
    if not loaded:
        return 0, 'EMPTY'
    if any(not material or material not in AUTO_DRYING_KNOWN_MATERIALS
           for material in loaded):
        return 45, 'UNKNOWN'
    has_pla = 'PLA' in loaded
    if has_pla and any(material != 'PLA' for material in loaded):
        return 50, 'PLA_MIXED'
    if has_pla:
        return 45, 'PLA_ONLY'
    return 60, 'HIGH_TEMP'
```

Implement `_auto_drying_slots()` on `BunnyAce` so each of four slots is considered loaded when either `inventory[index].status` or `_info['slots'][index].status` is not `empty`, and chooses `inventory.material` before hardware `type`.

- [ ] **Step 4: Run the policy tests and confirm GREEN**

Run: `python -m unittest tests.test_ace_driver_auto_drying.AutoDryingPolicyTests -v`

Expected: all policy cases pass, including unknown-material priority over PLA mixing and ignored empty slots.

- [ ] **Step 5: Commit the isolated policy**

```powershell
git add extras/ace.py tests/test_ace_driver_auto_drying.py
git commit -m "feat: add material-safe automatic drying policy"
```

### Task 2: Implement Persistent Controls and the Print Lifecycle

**Files:**
- Modify: `extras/ace.py` in `BunnyAce.__init__`, `_handle_ready`, `_handle_disconnect`, drying commands, and `get_status`
- Modify: `tests/test_ace_driver_auto_drying.py`
- Modify: `saved_variables.cfg`

- [ ] **Step 1: Write failing persistence, command, and ownership tests**

Add test doubles that record registered commands, timers, `SAVE_VARIABLE` scripts, ACE start/stop requests, and console messages. Add these tests:

```python
def test_enable_and_disable_persist_without_parameters(self):
    ace = make_auto_ace(enabled=False)
    ace.cmd_ACE_ENABLE_AUTO_DRYING(FakeCommand())
    self.assertTrue(ace.auto_drying_enabled)
    self.assertIn(
        'SAVE_VARIABLE VARIABLE=ace_auto_drying_enabled VALUE=True',
        ace.gcode.scripts,
    )
    ace.cmd_ACE_DISABLE_AUTO_DRYING(FakeCommand())
    self.assertFalse(ace.auto_drying_enabled)
    self.assertIn(
        'SAVE_VARIABLE VARIABLE=ace_auto_drying_enabled VALUE=False',
        ace.gcode.scripts,
    )

def test_two_printing_samples_start_owned_drying_once(self):
    ace = make_auto_ace(enabled=True, materials=["ABS"])
    tick(ace, "printing")
    self.assertEqual(ace.transport, [])
    tick(ace, "printing")
    self.assertEqual(ace.transport, [("start", 60, 1440)])
    self.assertTrue(ace.auto_drying_owned_by_auto)

def test_paused_keeps_drying_and_terminal_states_stop_owned_task(self):
    ace = running_auto_ace(temperature=50)
    tick(ace, "paused")
    self.assertEqual(ace.transport, [])
    tick(ace, "complete")
    self.assertEqual(ace.transport, [("stop",)])

def test_manual_drying_is_never_owned_or_stopped_at_print_end(self):
    ace = make_auto_ace(enabled=True, dryer_status="drying")
    tick(ace, "printing")
    tick(ace, "printing")
    tick(ace, "complete")
    self.assertEqual(ace.transport, [])

def test_manual_stop_suppresses_restart_for_current_job(self):
    ace = running_auto_ace(temperature=60)
    ace.cmd_ACE_STOP_DRYING(FakeCommand())
    ace.transport.clear()
    tick(ace, "printing")
    tick(ace, "printing")
    self.assertTrue(ace.auto_drying_suppressed_for_job)
    self.assertEqual(ace.transport, [])

def test_inventory_change_can_lower_but_not_raise_temperature(self):
    ace = running_auto_ace(temperature=60, materials=["ABS"])
    ace.set_materials(["ABS", "Mystery"])
    tick(ace, "printing")
    self.assertEqual(ace.transport, [("stop",), ("start", 45, 1440)])
    ace.transport.clear()
    ace.set_materials(["ABS"])
    tick(ace, "printing")
    self.assertEqual(ace.transport, [])

def test_empty_inventory_reports_once_and_does_not_start(self):
    ace = make_auto_ace(enabled=True, materials=[])
    tick(ace, "printing")
    tick(ace, "printing")
    tick(ace, "printing")
    self.assertEqual(ace.transport, [])
    self.assertEqual(ace.auto_drying_notice_id, 1)

def test_natural_expiry_renews_during_a_long_print(self):
    ace = running_auto_ace(temperature=60, materials=["ABS"])
    ace.set_dryer_status("stop")
    tick(ace, "printing")
    self.assertEqual(ace.transport, [("start", 60, 1440)])

def test_disconnect_retries_are_bounded_and_never_change_print_state(self):
    ace = make_auto_ace(enabled=True, materials=["ABS"], connected=False)
    tick(ace, "printing")
    tick(ace, "printing")
    for seconds in (30, 60, 90, 120):
        tick(ace, "printing", advance=seconds)
    self.assertEqual(ace.auto_drying_retry_count, 3)
    self.assertEqual(ace.print_stats.state, "printing")
    self.assertIn("ACE 未连接", ace.auto_drying_last_error)

def test_every_terminal_print_state_stops_only_owned_drying(self):
    for state in ("complete", "cancelled", "error", "standby"):
        with self.subTest(state=state):
            ace = running_auto_ace(temperature=45)
            tick(ace, state)
            self.assertEqual(ace.transport, [("stop",)])
```

- [ ] **Step 2: Run lifecycle tests and confirm RED**

Run:

```powershell
python -m unittest tests.test_ace_driver_auto_drying.AutoDryingLifecycleTests -v
```

Expected: failures for absent fields, commands, timer, ownership, suppression, and notices.

- [ ] **Step 3: Initialize and export one explicit state object**

Load `ace_auto_drying_enabled` with a default of `False`. Initialize the following fields in `BunnyAce.__init__`:

```python
self.auto_drying_enabled = bool(
    self.variables.get('ace_auto_drying_enabled', False))
self.auto_drying_active = False
self.auto_drying_owned_by_auto = False
self.auto_drying_suppressed_for_job = False
self.auto_drying_temperature = 0
self.auto_drying_reason = 'EMPTY'
self.auto_drying_print_state = 'standby'
self.auto_drying_last_error = ''
self.auto_drying_notice_id = 0
self.auto_drying_notice_message = ''
self.auto_drying_timer = None
self._auto_drying_job_active = False
self._auto_drying_print_samples = 0
self._auto_drying_pending_action = None
self._auto_drying_temperature_ceiling = 0
self._auto_drying_notices_seen = set()
self._auto_drying_retry_count = 0
self._auto_drying_next_retry = 0.
```

Expose a newly allocated dictionary from `get_status()` on every call:

```python
status['auto_drying'] = {
    'enabled': self.auto_drying_enabled,
    'active': self.auto_drying_active,
    'owned_by_auto': self.auto_drying_owned_by_auto,
    'suppressed_for_job': self.auto_drying_suppressed_for_job,
    'temperature': self.auto_drying_temperature,
    'reason': self.auto_drying_reason,
    'print_state': self.auto_drying_print_state,
    'last_error': self.auto_drying_last_error,
    'notice_id': self.auto_drying_notice_id,
    'notice_message': self.auto_drying_notice_message,
}
```

- [ ] **Step 4: Register the timer and strict no-parameter commands**

Register `ACE_ENABLE_AUTO_DRYING` and `ACE_DISABLE_AUTO_DRYING`. Both handlers must call `gcmd.get_command_parameters()` and reject any non-empty mapping, persist through `SAVE_VARIABLE`, update state immediately, and respond in Chinese. Register `_auto_drying_monitor` once in `_handle_ready`; unregister and null its timer in `_handle_disconnect`.

When disabling during an auto-owned task, queue one automatic stop. Do not stop a manual task.

- [ ] **Step 5: Implement the timer as a non-blocking state machine**

The timer returns `eventtime + 1.0` in every normal path and applies this exact transition order:

```text
read print_stats.state -> update public print_state -> refresh policy preview
terminal state with active job -> stop only owned task -> reset per-job state
paused with active job -> preserve state and renew only if owned drying naturally expired
printing sample 1 -> remember only
printing sample 2 -> open job, reset per-job notices/retries, then evaluate start
active job + disabled/suppressed/manual dryer -> do not start
active job + owned dryer + safer lower policy -> stop, then start at lower value
active job + owned dryer + expired 1440-minute cycle -> start another 1440-minute cycle
active job + disconnected/pending action/retry delay -> do not enqueue duplicates
```

Use callbacks from existing `send_request()` for automatic start and stop. Set `owned_by_auto=True` only after a successful start callback. On a non-zero response or exception, keep printing unchanged, set a Chinese `last_error`, publish one error notice, and allow at most three attempts for that print with at least 30 seconds between attempts.

Implement `_publish_auto_drying_notice(reason, message)` to increment `notice_id`, update `notice_message`, call `respond_info('ACE 自动烘干：' + message)`, and suppress duplicate reason keys through `_auto_drying_notices_seen`.

- [ ] **Step 6: Distinguish manual dryer commands from automatic ownership**

`cmd_ACE_START_DRYING` must remain a manual command and clear `owned_by_auto` after successful start. `cmd_ACE_STOP_DRYING` must set `suppressed_for_job=True` and clear automatic ownership when called during an active auto-owned print job. Internal auto stop/start helpers must never call the public G-code handlers, so they do not accidentally mark the task as manual.

- [ ] **Step 7: Add the persisted default without overwriting existing printer values**

Append only this distributable default to the repository copy of `saved_variables.cfg`:

```ini
ace_auto_drying_enabled = False
```

The installer must continue preserving the printer's existing `saved_variables.cfg`; this file is a documented new-install default, not a deployment replacement.

- [ ] **Step 8: Run driver regression tests and confirm GREEN**

Run:

```powershell
python -m unittest tests.test_ace_driver_auto_drying -v
python -m unittest tests.test_ace_driver_feed -v
python -m py_compile extras/ace.py
```

Expected: all automatic drying and existing feed/retract tests pass; compilation exits 0.

- [ ] **Step 9: Commit the driver lifecycle**

```powershell
git add extras/ace.py saved_variables.cfg tests/test_ace_driver_auto_drying.py
git commit -m "feat: follow print lifecycle with automatic drying"
```

### Task 3: Extend the Moonraker Contract

**Files:**
- Modify: `ace_status_integration/moonraker/ace_status.py`
- Modify: `tests/test_ace_status_component.py`

- [ ] **Step 1: Write failing normalization and command tests**

Add:

```python
def test_normalizes_auto_drying_state(self):
    status = ace_status.normalize_status(
        {"connected": True, "auto_drying": {
            "enabled": True, "active": True, "owned_by_auto": True,
            "suppressed_for_job": False, "temperature": 50,
            "reason": "PLA_MIXED", "print_state": "printing",
            "last_error": "", "notice_id": 7,
            "notice_message": "检测到 PLA 与其他材料混装",
        }}, {}, {}, {}, printing=True)
    self.assertEqual(status["auto_drying"]["temperature"], 50)
    self.assertEqual(status["auto_drying"]["reason"], "PLA_MIXED")
    self.assertEqual(status["auto_drying"]["notice_id"], 7)

def test_auto_drying_switch_commands_are_strict_and_allowed_while_printing(self):
    self.assertEqual(
        ace_status.build_gcode(
            {"command": "ACE_ENABLE_AUTO_DRYING", "params": {}},
            printing=True),
        "ACE_ENABLE_AUTO_DRYING")
    self.assertEqual(
        ace_status.build_gcode(
            {"command": "ACE_DISABLE_AUTO_DRYING", "params": {}},
            printing=True),
        "ACE_DISABLE_AUTO_DRYING")
    with self.assertRaises(ace_status.AceRequestError):
        ace_status.build_gcode({
            "command": "ACE_ENABLE_AUTO_DRYING", "params": {"TEMP": 60}})
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m unittest tests.test_ace_status_component -v`

Expected: missing `auto_drying` response and unsupported commands.

- [ ] **Step 3: Normalize all fields with safe defaults**

Add `_normalize_auto_drying(value)` returning this exact schema:

```python
return {
    "enabled": _safe_bool(raw.get("enabled")),
    "active": _safe_bool(raw.get("active")),
    "owned_by_auto": _safe_bool(raw.get("owned_by_auto")),
    "suppressed_for_job": _safe_bool(raw.get("suppressed_for_job")),
    "temperature": _safe_int(raw.get("temperature")),
    "reason": str(raw.get("reason") or "EMPTY"),
    "print_state": str(raw.get("print_state") or "standby"),
    "last_error": str(raw.get("last_error") or ""),
    "notice_id": _safe_int(raw.get("notice_id")),
    "notice_message": str(raw.get("notice_message") or ""),
}
```

Insert it into `normalize_status()` as `"auto_drying": _normalize_auto_drying(ace.get("auto_drying"))`.

- [ ] **Step 4: Whitelist strict enable and disable commands**

Add both commands with `_build_no_params`. Keep them out of the `write_commands` printing block so the user can toggle the feature during a print. Add both commands to the disconnected-device allowlist because they update a host-side persistent preference; disabling while ACE USB is offline must still suppress later automatic starts. The driver records a warning if an auto-owned dryer cannot be stopped while disconnected, but the preference change itself succeeds.

- [ ] **Step 5: Run the full Python suite and commit**

Run:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python -m py_compile ace_status_integration/moonraker/ace_status.py
```

Expected: all tests pass and compilation exits 0.

```powershell
git add ace_status_integration/moonraker/ace_status.py tests/test_ace_status_component.py
git commit -m "feat: expose automatic drying through Moonraker"
```

### Task 4: Add Typed Fluidd State and Display Helpers

**Files:**
- Modify: `fluidd-source-overlay/src/types/acePro.ts`
- Modify: `fluidd-source-overlay/src/util/acepro.ts`
- Modify: `fluidd-source-overlay/src/util/acepro.test.ts`
- Synchronize the same files into: `C:/Users/Luomo/Documents/ace profluidd上的可视化界面/fluidd-develop/src/`

- [ ] **Step 1: Write failing adapter and label tests in both source trees**

Add API-state assertions:

```typescript
it('normalizes automatic drying without recalculating temperature', () => {
  const state = resolveAceProApiState({
    api_version: 1,
    driver: 'ACEPROSV08',
    auto_drying: {
      enabled: true,
      active: true,
      owned_by_auto: true,
      suppressed_for_job: false,
      temperature: 50,
      reason: 'PLA_MIXED',
      print_state: 'printing',
      last_error: '',
      notice_id: 9,
      notice_message: '混装提示',
    },
  })
  expect(state.autoDrying.temperature).toBe(50)
  expect(state.autoDrying.reason).toBe('PLA_MIXED')
  expect(autoDryingStatusLabel(state.autoDrying)).toBe('运行中 50°C')
  expect(autoDryingBasisLabel(state.autoDrying)).toBe('50°C · PLA 混装')
})

it('uses explicit unknown defaults instead of inventing disabled backend state', () => {
  const state = resolveAceProApiState({ api_version: 1, driver: 'ACEPROSV08' })
  expect(state.autoDrying.available).toBe(false)
  expect(autoDryingStatusLabel(state.autoDrying)).toBe('状态不可用')
})

it('uses the approved safety warning text', () => {
  expect(autoDryingWarningMessage('PLA_MIXED')).toBe(
    '检测到 PLA 与其他材料混装，自动烘干使用 50°C 以保护 PLA；其他高温材料的烘干效果可能受限。')
  expect(autoDryingWarningMessage('UNKNOWN')).toBe(
    '检测到未知材料，将以 45°C 进行自动烘干，部分材料的烘干效果可能受限。')
})
```

- [ ] **Step 2: Run Vitest and confirm RED**

Run from `fluidd-develop`:

```powershell
pnpm.cmd test:unit -- src/util/acepro.test.ts --run
```

Expected: type or import failures for missing `autoDrying` and label helpers.

- [ ] **Step 3: Define the typed contract**

Add:

```typescript
export type AceProAutoDryingReason = 'EMPTY' | 'UNKNOWN' | 'PLA_MIXED' | 'PLA_ONLY' | 'HIGH_TEMP'

export interface AceProAutoDryingState {
  available: boolean;
  enabled: boolean;
  active: boolean;
  ownedByAuto: boolean;
  suppressedForJob: boolean;
  temperature: number;
  reason: AceProAutoDryingReason;
  printState: string;
  lastError: string;
  noticeId: number;
  noticeMessage: string;
}
```

Add `autoDrying: AceProAutoDryingState` to `AceProResolvedState`.

- [ ] **Step 4: Normalize API and direct-printer fallback state**

Map snake_case backend fields to the typed camelCase fields. `available` is `true` only when `auto_drying` is an object; absent legacy state must remain unavailable. Add label helpers with these fixed mappings:

```typescript
const AUTO_DRYING_BASIS = {
  EMPTY: '未检测到耗材',
  UNKNOWN: '未知材料',
  PLA_MIXED: 'PLA 混装',
  PLA_ONLY: '全部 PLA',
  HIGH_TEMP: '高温材料',
} as const

export function autoDryingStatusLabel (state: AceProAutoDryingState): string {
  if (!state.available) return '状态不可用'
  if (!state.enabled) return '已关闭'
  if (state.active) return `运行中 ${state.temperature}°C`
  return '已开启'
}

export function autoDryingBasisLabel (state: AceProAutoDryingState): string {
  const basis = AUTO_DRYING_BASIS[state.reason]
  return state.temperature > 0 ? `${state.temperature}°C · ${basis}` : basis
}

export function autoDryingWarningMessage (reason: AceProAutoDryingReason): string {
  if (reason === 'PLA_MIXED') {
    return '检测到 PLA 与其他材料混装，自动烘干使用 50°C 以保护 PLA；其他高温材料的烘干效果可能受限。'
  }
  if (reason === 'UNKNOWN') {
    return '检测到未知材料，将以 45°C 进行自动烘干，部分材料的烘干效果可能受限。'
  }
  return ''
}
```

- [ ] **Step 5: Run Vitest and type checking, then commit**

Run from `fluidd-develop`:

```powershell
pnpm.cmd test:unit -- src/util/acepro.test.ts --run
pnpm.cmd type-check
```

Expected: tests and type checking pass.

```powershell
git add fluidd-source-overlay/src/types/acePro.ts fluidd-source-overlay/src/util/acepro.ts fluidd-source-overlay/src/util/acepro.test.ts
git commit -m "feat: normalize automatic drying for Fluidd"
```

### Task 5: Implement Fluidd Controls, Notices, and Compact Layout

**Files:**
- Modify: `fluidd-source-overlay/src/mixins/acePro.ts`
- Modify: `fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue`
- Modify: `fluidd-source-overlay/src/util/acepro.test.ts`
- Synchronize the same files into: `C:/Users/Luomo/Documents/ace profluidd上的可视化界面/fluidd-develop/src/`

- [ ] **Step 1: Add failing notice de-duplication helper tests**

Add a pure helper to the utility test contract:

```typescript
it('emits each increasing backend notice exactly once', () => {
  expect(shouldShowAceNotice(0, 0)).toBe(false)
  expect(shouldShowAceNotice(4, 4)).toBe(false)
  expect(shouldShowAceNotice(5, 4)).toBe(true)
  expect(shouldShowAceNotice(1, 5)).toBe(false)
})
```

Expected helper:

```typescript
export function shouldShowAceNotice (incoming: number, seen: number): boolean {
  return incoming > 0 && incoming > seen
}
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `pnpm.cmd test:unit -- src/util/acepro.test.ts --run`

Expected: missing `shouldShowAceNotice` import or function.

- [ ] **Step 3: Handle backend notices through Fluidd's notification store**

Add `aceProLastNoticeId = 0` to the mixin. After accepting a non-stale API response, compare the incoming ID, update the seen ID before dispatch, and execute:

```typescript
await this.$typedDispatch('notifications/pushNotification', {
  id: `ace-auto-drying-${notice.noticeId}`,
  type: notice.lastError ? 'error' : 'info',
  title: 'ACE Pro 自动烘干',
  description: notice.noticeMessage || notice.lastError,
  snackbar: true,
  clear: true,
})
```

Do not replay prior notices after a component remount: initialize `aceProLastNoticeId` from the first successful poll without displaying it, then display only later increasing IDs.

- [ ] **Step 4: Add a guarded automatic drying toggle**

Implement:

```typescript
async toggleAceProAutoDrying (enabled: boolean) {
  if (enabled && ['PLA_MIXED', 'UNKNOWN'].includes(this.aceProState.autoDrying.reason)) {
    const accepted = await this.$confirm(
      autoDryingWarningMessage(this.aceProState.autoDrying.reason),
      { title: 'ACE Pro 自动烘干', color: 'card-heading', icon: '$warning' }
    )
    if (!accepted) return
  }
  const command = enabled
    ? 'ACE_ENABLE_AUTO_DRYING'
    : 'ACE_DISABLE_AUTO_DRYING'
  await this.executeAceCommand(command, {}, WAIT_DRYER_ACTION, command)
}
```

Disable the switch when the API is unavailable, a dryer action is pending, or the driver does not expose `auto_drying`. Do not optimistically mutate the switch; wait for the next backend response.

- [ ] **Step 5: Render identical status in the top area and dryer controls**

Add one top status item labelled `自动烘干` using `autoDryingStatusLabel`. In the dryer panel add a `v-switch` labelled `自动跟随打印`, followed by `autoDryingBasisLabel` and `lastError` when non-empty. Keep manual temperature, duration, start, and stop controls unchanged.

- [ ] **Step 6: Correct the endless-spool layout**

Remove `margin-left: auto` from `.acepro-quick-actions__switch`. Keep desktop sizing content-based:

```css
.acepro-quick-actions__switch {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  min-height: 30px;
}
```

Preserve the existing `@media (max-width: 600px)` rule that sets the switch to `width: 100%`. The switch must immediately follow `诊断传感器` in DOM order.

- [ ] **Step 7: Run frontend tests and static checks**

Run from `fluidd-develop`:

```powershell
pnpm.cmd test:unit -- src/util/acepro.test.ts --run
pnpm.cmd type-check
pnpm.cmd lint
```

Expected: all commands exit 0; no direct frontend material-to-temperature function is introduced.

- [ ] **Step 8: Commit the Fluidd interaction and layout**

```powershell
git add fluidd-source-overlay/src/mixins/acePro.ts fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue fluidd-source-overlay/src/util/acepro.test.ts
git commit -m "feat: control automatic drying from Fluidd"
```

### Task 6: Keep `/ace.html` Functionally Equivalent

**Files:**
- Modify: `ace_status_integration/web/ace.html`
- Modify: `ace_status_integration/web/ace-dashboard.js`
- Modify: `ace_status_integration/web/ace-dashboard.css`
- Create: `tests/web/auto-drying-page.test.mjs`

- [ ] **Step 1: Write failing static page contract tests**

Create:

```javascript
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('standalone page exposes automatic drying status and switch', async () => {
  const html = await readFile('ace_status_integration/web/ace.html', 'utf8')
  assert.match(html, /自动烘干/)
  assert.match(html, /自动跟随打印/)
  assert.match(html, /toggleAutoDrying/)
  assert.match(html, /autoDryingStatusText/)
  assert.match(html, /autoDryingBasisText/)
})

test('standalone client sends only strict switch commands', async () => {
  const source = await readFile('ace_status_integration/web/ace-dashboard.js', 'utf8')
  assert.match(source, /ACE_ENABLE_AUTO_DRYING/)
  assert.match(source, /ACE_DISABLE_AUTO_DRYING/)
  assert.doesNotMatch(source, /ACE_ENABLE_AUTO_DRYING TEMP=/)
})
```

- [ ] **Step 2: Run Node tests and confirm RED**

Run: `node --test tests/web/auto-drying-page.test.mjs`

Expected: missing labels, handler, state text, and commands.

- [ ] **Step 3: Add standalone state and backend-only status rendering**

Initialize:

```javascript
autoDrying: {
  available: false,
  enabled: false,
  active: false,
  owned_by_auto: false,
  suppressed_for_job: false,
  temperature: 0,
  reason: 'EMPTY',
  print_state: 'standby',
  last_error: '',
  notice_id: 0,
  notice_message: ''
},
lastAutoDryingNoticeId: null,
```

When `updateStatus(data)` receives `data.auto_drying`, merge it without deriving a temperature from slots. On the first received notice ID, store it silently; on later increasing IDs, call `showNotification()` once.

- [ ] **Step 4: Add warning confirmation and strict command toggle**

Implement:

```javascript
async toggleAutoDrying() {
  const enabling = !this.autoDrying.enabled;
  if (enabling && ['PLA_MIXED', 'UNKNOWN'].includes(this.autoDrying.reason)) {
    const message = this.autoDrying.reason === 'PLA_MIXED'
      ? '检测到 PLA 与其他材料混装，自动烘干使用 50°C 以保护 PLA；其他高温材料的烘干效果可能受限。'
      : '检测到未知材料，将以 45°C 进行自动烘干，部分材料的烘干效果可能受限。';
    if (!window.confirm(message)) return;
  }
  const command = enabling
    ? 'ACE_ENABLE_AUTO_DRYING'
    : 'ACE_DISABLE_AUTO_DRYING';
  await this.executeCommand(command, {});
  await this.loadStatus();
}
```

Add computed status and basis text using the same five mappings as Fluidd. Do not reuse the existing active-slot `dryerTemperatureForMaterial()` for automatic drying; it remains only a manual-input convenience.

- [ ] **Step 5: Add compact markup and responsive CSS**

Place the toggle in the dryer card, and the status in the top device card. Use a native button or checkbox with `aria-pressed`/accessible label. Ensure status text wraps and the switch cannot overlap start/stop buttons at 360 px.

- [ ] **Step 6: Run standalone tests and commit**

Run:

```powershell
node --test tests/web/auto-drying-page.test.mjs
python -m unittest tests.test_ace_status_component -v
```

Expected: tests pass.

```powershell
git add ace_status_integration/web tests/web/auto-drying-page.test.mjs
git commit -m "feat: add automatic drying to standalone dashboard"
```

### Task 7: Rebuild Fluidd v1.37.2 Without Stale Assets

**Files:**
- Modify synchronized files under: `C:/Users/Luomo/Documents/ace profluidd上的可视化界面/fluidd-develop/src/`
- Replace: `fluidd-dist/`
- Modify: `manifest.sha256`

- [ ] **Step 1: Verify source baseline and overlay parity**

Run:

```powershell
Set-Location 'C:\Users\Luomo\Documents\ace profluidd上的可视化界面\fluidd-develop'
node.exe -p "require('./package.json').version"
git status --short
```

Expected: version `1.37.2`; inspect all pre-existing changes before copying and never overwrite unrelated user edits.

Synchronize each reviewed overlay file to the matching `fluidd-develop/src` path with `Copy-Item -LiteralPath` only after comparing hashes or `git diff --no-index`.

- [ ] **Step 2: Run the complete Fluidd verification**

```powershell
pnpm.cmd test:unit -- src/util/acepro.test.ts --run
pnpm.cmd type-check
pnpm.cmd lint
pnpm.cmd build
```

Expected: all commands exit 0; `dist/index.html`, `dist/sw.js`, the ACE card JavaScript chunk, and the ACE card CSS chunk exist.

- [ ] **Step 3: Replace the distribution as one complete set**

Move the existing repository `fluidd-dist` to a timestamped local staging backup under `.temporary/` without deleting it. Copy the newly generated `fluidd-develop/dist` directory to `fluidd-dist`. Verify every asset referenced by `index.html` and `sw.js` exists and verify there is exactly one current `AceProCard-*.js` and one `AceProCard-*.css`.

- [ ] **Step 4: Regenerate and verify checksums**

From Git Bash at the repository root:

```bash
find . -type f \
  ! -path './.git/*' \
  ! -path './.temporary/*' \
  ! -name 'manifest.sha256' \
  -print0 | sort -z | xargs -0 sha256sum > manifest.sha256
sha256sum -c manifest.sha256
```

Expected: every tracked payload file reports `OK` and no `.temporary` path appears in the manifest.

- [ ] **Step 5: Run installer regression tests**

```bash
bash tests/installer/test-installer.sh
bash tests/installer/test-install-scopes.sh
bash tests/installer/test-install-failure.sh
```

Expected: normal install, forced install, driver-only, card-only, rollback, and failure recovery all pass; user `ace.cfg` and `saved_variables.cfg` remain preserved.

- [ ] **Step 6: Commit the complete build set**

```powershell
git add fluidd-dist manifest.sha256
git commit -m "build: package automatic drying interface"
```

### Task 8: Update Versioned Documentation and Release Metadata

**Files:**
- Modify: `VERSION`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Create: `docs/DRIVER-v1.1.0.zh-CN.md`
- Modify: `manifest.sha256`

- [ ] **Step 1: Add a failing documentation contract test**

Extend `tests/test_ace_status_component.py` or create `tests/test_release_docs.py` with:

```python
def test_v110_documents_auto_drying_safety_rules(self):
    root = pathlib.Path(__file__).parents[1]
    self.assertEqual((root / "VERSION").read_text(encoding="utf-8").strip(), "1.1.0")
    text = (root / "README.md").read_text(encoding="utf-8")
    for phrase in [
        "自动跟随打印", "全部 PLA：45°C", "PLA 与其他材料混装：50°C",
        "未知材料：45°C", "高温材料：60°C", "手动启动的烘干不会被自动停止",
    ]:
        self.assertIn(phrase, text)
```

- [ ] **Step 2: Run and confirm RED**

Run: `python -m unittest tests.test_release_docs -v`

Expected: version or required documentation phrases are absent.

- [ ] **Step 3: Document operation and limits**

Set `VERSION` to `1.1.0`. Add a changelog section covering the automatic lifecycle, temperature priority, manual ownership protection, retry behavior, top status, warning confirmation, notice de-duplication, and endless-spool alignment fix. State explicitly that this version supports one ACE Pro with `szkrisz/ACEPROSV08`, does not support `Kobra-S1/ACEPRO`, and targets Fluidd v1.37.2.

Document that automatic drying is off by default, enabling persists across restart, `paused` keeps drying, terminal print states stop only auto-owned drying, a manual stop suppresses restart for that print, and unknown/empty inventory behavior.

- [ ] **Step 4: Run docs tests, regenerate checksums, and commit**

Run:

```powershell
python -m unittest tests.test_release_docs -v
```

Regenerate and verify `manifest.sha256` with the Task 7 command.

```powershell
git add VERSION CHANGELOG.md README.md docs/DRIVER-v1.1.0.zh-CN.md tests/test_release_docs.py manifest.sha256
git commit -m "docs: document automatic print drying"
```

Do not push this branch or create a GitHub release unless the user explicitly requests publication after reviewing the installed result.

### Task 9: Perform Visual and Browser Regression Verification

**Files:**
- Modify only when verification exposes a tested defect
- Optional local evidence: `.temporary/visual/` (excluded from release and checksums)

- [ ] **Step 1: Start the verified Fluidd production preview**

Run from `fluidd-develop`:

```powershell
pnpm.cmd preview --host 127.0.0.1 --port 4173
```

Expected: preview remains running at `http://127.0.0.1:4173` and serves the latest build.

- [ ] **Step 2: Mock normal and edge backend states**

Verify at least these API payloads: disabled, enabled idle, active 45°C PLA, active 50°C PLA mix, active 60°C high-temperature materials, unknown material warning, empty inventory notice, disconnected ACE, missing legacy `auto_drying`, and a newer `notice_id`.

- [ ] **Step 3: Measure compact layout at real card widths**

At desktop, 460 px card width, and 360 px viewport verify:

```javascript
const quick = document.querySelector('.acepro-quick-actions')
const endless = document.querySelector('.acepro-quick-actions__switch')
const rect = endless.getBoundingClientRect()
if (rect.right > quick.getBoundingClientRect().right + 1) throw new Error('endless switch overflow')
if (endless.scrollWidth > endless.clientWidth) throw new Error('endless switch text clipped')
```

Confirm the endless-spool switch follows the sensor diagnostics control, desktop uses the same flex row, narrow mobile wraps to a full row, and no button or status overlaps.

- [ ] **Step 4: Verify interaction behavior**

Confirm one confirmation dialog for enabling under `PLA_MIXED` and `UNKNOWN`, no dialog for `PLA_ONLY` or `HIGH_TEMP`, no optimistic switch change before backend confirmation, one notification per increasing `notice_id`, and no replay of the latest notice after refresh.

- [ ] **Step 5: Verify `/ace.html` at desktop and mobile widths**

Repeat state and interaction checks at 1366x768 and 360x800. Confirm top status, basis text, dryer switch, manual dryer controls, slots, endless spool, sensors, feed/retract, and diagnostics remain available and no horizontal overflow appears.

- [ ] **Step 6: Stop preview and retain only privacy-safe local evidence**

Stop the preview process. Screenshots must not contain printer IP, username, tokens, local paths, or device credentials. Do not add screenshots to Git without a separate user request.

### Task 10: Run Final Local Verification and Prepare Safe Printer Deployment

**Files:**
- Modify only if a verified defect is found

- [ ] **Step 1: Run the final local verification matrix**

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python -m py_compile extras/ace.py ace_status_integration/moonraker/ace_status.py
node --test tests/web/auto-drying-page.test.mjs
```

From `fluidd-develop`:

```powershell
pnpm.cmd test:unit -- src/util/acepro.test.ts --run
pnpm.cmd type-check
pnpm.cmd lint
pnpm.cmd build
```

From Git Bash in the release repository:

```bash
bash tests/installer/test-installer.sh
bash tests/installer/test-install-scopes.sh
bash tests/installer/test-install-failure.sh
sha256sum -c manifest.sha256
```

Expected: every command exits 0 and `git status --short` contains only intentional local work, if any.

- [ ] **Step 2: Audit release boundaries**

Search tracked files for `192.168.`, passwords, private keys, GitHub tokens, absolute user paths, `.temporary`, and stale hashed Fluidd chunks. Confirm GPL/third-party notices remain intact and no `Kobra-S1` command schema appears in runtime code.

- [ ] **Step 3: Stop before remote writes and obtain deployment confirmation**

Report local verification results and exact commits. Do not connect for write operations, deploy to the printer, restart a service, or push GitHub until the user confirms the reviewed local build should be installed.

### Task 11: Deploy to the Printer With Mandatory Before/After Backups

**Files:**
- Remote only after explicit confirmation: ACE driver, Moonraker component, standalone page, and complete Fluidd distribution
- Local backup archive root: `C:/Users/Luomo/桌面/打印机配置备份`

- [ ] **Step 1: Perform read-only preflight**

Read `print_stats`, Klipper/Moonraker service status, current ACE driver path and version, current Fluidd version, `[ace_status]` loading state, and available disk space. If `print_stats.state` is `printing` or `paused`, stop and do not deploy or restart services.

- [ ] **Step 2: Create the mandatory before-change backup**

Run exactly once with a real detailed reason:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Luomo\Documents\ace profluidd上的可视化界面\printer-tools\Backup-PrinterConfig.ps1" -Label before-change -Reason "变更前：准备安装ACEPROSV08自动跟随打印烘干状态机、Moonraker命令接口及Fluidd和独立页面控件，并修复无限续料开关布局；预期保留现有ace.cfg与saved_variables.cfg且支持完整回滚。"
```

Expected: script succeeds and prints a new timestamped directory under `C:\Users\Luomo\桌面\打印机配置备份\2026\07`; that directory contains `备份说明.txt`, `backup-manifest.json`, and valid `SHA256SUMS`. If this fails, stop immediately and perform no remote write.

- [ ] **Step 3: Install through the tested transactional installer**

Upload or update the Git checkout without deleting the existing installation. Run the installer's normal combined driver-and-card option so it creates its own `old` rollback archive. Preserve remote `ace.cfg` and `saved_variables.cfg`; do not execute `T0`-`T3`, feed, retract, cutter, or toolchange commands.

- [ ] **Step 4: Restart only after a second print-state check**

Query `print_stats` again immediately before restarting Klipper or Moonraker. Restart only while idle. Validate Klipper reaches `ready`, Moonraker remains `active`, `/server/ace/status` returns API version 1 with `auto_drying`, Fluidd loads without a blank screen or browser-console exception, and `/ace.html` renders.

- [ ] **Step 5: Perform read-only functional checks**

Confirm switch state persists through a status refresh, top and dryer status match, current dryer/manual ownership status is not altered, both sensor displays still report, all four slots remain present, and installer rollback metadata exists. Do not start a print or dryer automatically as deployment verification.

- [ ] **Step 6: Create the mandatory after-change backup**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Luomo\Documents\ace profluidd上的可视化界面\printer-tools\Backup-PrinterConfig.ps1" -Label after-change -Reason "变更后：已安装ACEPROSV08自动跟随打印烘干驱动、Moonraker状态与控制接口、Fluidd卡片和中文独立页面，并完成Python语法、服务就绪、API字段、页面加载及现有配置保留验证。"
```

Expected: a second timestamped directory contains the same manifest, explanation, and checksum artifacts. If this backup fails, report the exact remote state and do not claim deployment complete.

- [ ] **Step 7: Report deployment evidence and remaining physical validation**

List both backup directories and their reasons, installed versions and hashes, service/API/browser results, rollback location, and the fact that no feed/retract/cutter/toolchange physical action was run. Ask the user to validate the next real print while observing only the first automatic start and final automatic stop; GitHub publication remains a separate explicit decision.
