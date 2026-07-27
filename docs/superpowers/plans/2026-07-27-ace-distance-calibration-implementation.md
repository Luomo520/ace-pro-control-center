# ACE Distance Calibration and Preload Parking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe shared feed/retract calibration, per-slot estimated preload parking, and confirmed cold preload-to-toolhead behavior while preserving full T0-T3 toolchange semantics.

**Architecture:** Keep hardware ownership in `extras/ace.py`, expose only normalized state and whitelisted commands through Moonraker, and make Fluidd plus `/ace.html` consume the same contract. Persist a four-slot position array and calibration record in Klipper saved variables; all calibration movement is segmented and sensor bounded, while normal toolchanges remain automatic.

**Tech Stack:** Klipper Python extras, Moonraker Python component, Vue 2/TypeScript Fluidd, standalone Vue JavaScript, Python `unittest`, Vitest/Jest-compatible Fluidd tests, Node test runner, Bash installer tests.

---

## File Map

- Modify `extras/ace.py`: driver state, calibration state machine, preload, parking, recovery, cancellation, sensor debounce, status contract.
- Modify `ace.cfg`: corrected distance comments, calibration parameters, split toolchange/preload macro behavior.
- Create `tests/test_ace_driver_calibration.py`: pure distance, persistence, calibration, preload and recovery tests.
- Modify `tests/test_ace_driver_feed.py`: normal two-stage feed and retract regressions.
- Modify `tests/test_ace_status_component.py`: Moonraker state and command whitelist tests.
- Modify `ace_status_integration/moonraker/ace_status.py`: normalized calibration/slot-position state and strict command builders.
- Modify `ace_status_integration/web/ace-dashboard.js`: standalone calibration/preload state and actions.
- Modify `ace_status_integration/web/ace-dashboard.css`: compact wizard and status presentation.
- Modify `ace_status_integration/web/ace.html`: calibration dialog mount points if required by existing template structure.
- Modify `tests/web/auto-drying-page.test.mjs`: extend standalone contract checks without regressing drying.
- Create `tests/web/calibration-page.test.mjs`: standalone calibration/preload flow checks.
- Modify `fluidd-source-overlay/src/types/acePro.ts`: typed calibration and per-slot positions.
- Modify `fluidd-source-overlay/src/util/acepro.ts`: normalization and labels.
- Modify `fluidd-source-overlay/src/util/acepro.test.ts`: status normalization tests.
- Modify `fluidd-source-overlay/src/mixins/acePro.ts`: confirmation and commands.
- Modify `fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue`: compact calibration/preload UI.
- Modify `fluidd-source-overlay/src/views/AcePro.vue`: full-size matching UI.
- Mirror Fluidd source edits under `../fluidd-develop/src/...`, build there, then sync the verified source overlay and `fluidd-dist` back into this repository.
- Modify `tests/web/fluidd-card-layout.test.mjs`: layout and required-control checks.
- Modify `README.md`, `CHANGELOG.md`, `docs/DRIVER-v1.1.0.zh-CN.md`: configuration, workflow, limitations and recovery documentation.
- Modify `manifest.sha256`: regenerate only after final build and package verification.

### Task 1: Lock Down Existing Motion Regressions

**Files:**
- Modify: `tests/test_ace_driver_feed.py`
- Modify: `extras/ace.py`

- [ ] **Step 1: Add failing tests for fast plus final-100-mm feed and timeout use**

```python
def test_continuous_mode_uses_fast_and_100mm_approach_requests(self):
    ace = make_ace(intermittent=False)
    ace.feed_approach_length = 100.0
    calls = []
    ace._feed = lambda index, length, speed, stop_sensor=None: (
        calls.append((length, speed, stop_sensor)) or {}
    )
    ace._sensor_present = lambda _name: len(calls) == 2

    ace._feed_until_sensor(0, "extruder_sensor", 1200, 160,
                           "送料 %.1f mm 后未触发")

    self.assertEqual(calls[0][:2], (1100.0, 160))
    self.assertEqual(calls[1][:2], (100.0, 25.0))

def test_feed_timeout_uses_extruder_sensor_timeout(self):
    ace = make_ace(intermittent=False)
    ace.extruder_sensor_timeout = 17.0
    self.assertEqual(ace._sensor_confirmation_timeout(), 17.0)
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `python -m unittest tests.test_ace_driver_feed -v`  
Expected: FAIL because continuous mode sends one 1200 mm request and no timeout helper exists.

- [ ] **Step 3: Implement two-stage continuous feed without 100 mm chunk pauses**

```python
def _feed_continuously_until_sensor(self, tool, sensor_name,
                                    total_length, speed, failure_message):
    approach = min(self.feed_approach_length, float(total_length))
    fast = float(total_length) - approach
    fed = 0.0
    for length, phase_speed, phase in (
            (fast, speed, 'ACE_FEED_FAST'),
            (approach, self.feed_approach_speed, 'ACE_FEED_APPROACH')):
        if length <= 0 or self._sensor_present(sensor_name):
            continue
        result = self._feed(tool, length, phase_speed,
                            stop_sensor=sensor_name)
        fed += length
        if result.get('stopped_by_sensor') or self._sensor_present(sensor_name):
            return fed
    return self._run_limited_feed_compensation(
        tool, sensor_name, fed, failure_message)
```

Add `_sensor_confirmation_timeout()` returning `self.extruder_sensor_timeout` and use it in bounded sensor waits.

- [ ] **Step 4: Remove the duplicate `_on_toolhead_move` implementation and invalid `_endless_spool_check_distance` call**

Keep one callback that delegates to the tested endless-spool monitor and never references an undefined method.

- [ ] **Step 5: Run feed and compile tests**

Run: `python -m unittest tests.test_ace_driver_feed -v`  
Expected: PASS.  
Run: `python -m py_compile extras/ace.py`  
Expected: exit 0.

- [ ] **Step 6: Commit the regression foundation**

```bash
git add extras/ace.py tests/test_ace_driver_feed.py
git commit -m "fix: harden ACE feed motion stages"
```

### Task 2: Add Per-Slot Position Persistence and Migration

**Files:**
- Create: `tests/test_ace_driver_calibration.py`
- Modify: `extras/ace.py`
- Modify: `saved_variables.cfg`

- [ ] **Step 1: Add failing state migration tests**

```python
def test_slot_positions_default_to_unknown_except_confirmed_current_slot(self):
    ace = make_state_ace(current_index=1, legacy_position="nozzle",
                         upper=True, lower=True)
    ace._load_slot_positions()
    self.assertEqual(ace.slot_positions,
                     ["unknown", "nozzle", "unknown", "unknown"])

def test_two_slots_can_retain_independent_positions(self):
    ace = make_state_ace()
    ace._set_slot_position(0, "preload_parked_estimated", persist=False)
    ace._set_slot_position(2, "nozzle", persist=False)
    self.assertEqual(ace.slot_positions[0], "preload_parked_estimated")
    self.assertEqual(ace.slot_positions[2], "nozzle")
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m unittest tests.test_ace_driver_calibration -v`  
Expected: FAIL because the driver only has global `ace_filament_pos`.

- [ ] **Step 3: Implement validated per-slot positions**

```python
SLOT_POSITIONS = {
    'internal_or_unknown', 'preload_parked_estimated',
    'upper_sensor', 'toolhead', 'nozzle', 'unknown',
}

def _set_slot_position(self, index, position, persist=True):
    if index < 0 or index >= 4 or position not in SLOT_POSITIONS:
        raise self.printer.command_error('ACE：槽位位置状态无效')
    self.slot_positions[index] = position
    if persist:
        self._save_json_variable('ace_slot_positions', self.slot_positions)
```

Load a four-item list from `ace_slot_positions`; migrate only the uniquely known current slot from legacy `ace_filament_pos`, and mark all ambiguous slots `unknown`.

- [ ] **Step 4: Expose slot positions in `get_status()`**

```python
status['slot_positions'] = list(self.slot_positions)
status['filament_position'] = (
    self.slot_positions[current_index]
    if 0 <= current_index < 4 else 'unknown')
```

- [ ] **Step 5: Run state and existing tests**

Run: `python -m unittest tests.test_ace_driver_calibration tests.test_ace_driver_feed -v`  
Expected: PASS.

- [ ] **Step 6: Commit slot state support**

```bash
git add extras/ace.py saved_variables.cfg tests/test_ace_driver_calibration.py
git commit -m "feat: persist per-slot ACE filament positions"
```

### Task 3: Implement Pure Calibration Math and Persistent Record

**Files:**
- Modify: `tests/test_ace_driver_calibration.py`
- Modify: `extras/ace.py`
- Modify: `ace.cfg`

- [ ] **Step 1: Add failing distance and invalidation tests**

```python
def test_parking_distance_uses_feed_upper_bound_bowden_and_margin(self):
    result = ace_driver.calculate_parking_distance(1205, 190, 20, 1600)
    self.assertEqual(result, 1035)

def test_parking_distance_rejects_out_of_bounds_result(self):
    with self.assertRaises(ValueError):
        ace_driver.calculate_parking_distance(100, 190, 20, 1600)

def test_calibration_invalidates_when_bowden_changes(self):
    record = make_record(bowden_tube_length=190)
    self.assertFalse(ace_driver.calibration_is_valid(record, 200, 20, 1))
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m unittest tests.test_ace_driver_calibration -v`  
Expected: FAIL because helpers and record do not exist.

- [ ] **Step 3: Implement pure helpers and config validation**

```python
CALIBRATION_FORMAT_VERSION = 1

def calculate_parking_distance(feed_upper, bowden, margin, max_distance):
    result = float(feed_upper) - float(bowden) + float(margin)
    if result <= 0 or result > float(max_distance):
        raise ValueError('calculated parking distance is outside safe bounds')
    return result
```

Parse `calibration_speed`, `calibration_chunk_length`, `calibration_final_chunk_length`, and `five_way_parking_margin` with positive/minimum validation. Use `toolchange_load_length + feed_slip_compensation_length` as `max_distance`.

- [ ] **Step 4: Implement preview and confirmed persistence**

Keep `_calibration_preview` in memory. Persist `ace_calibration` only from a save command after preview state is complete; never overwrite a valid record on failure.

- [ ] **Step 5: Run focused tests and compile**

Run: `python -m unittest tests.test_ace_driver_calibration -v`  
Expected: PASS.  
Run: `python -m py_compile extras/ace.py`  
Expected: exit 0.

- [ ] **Step 6: Commit calibration data model**

```bash
git add ace.cfg extras/ace.py tests/test_ace_driver_calibration.py
git commit -m "feat: add ACE calibration data model"
```

### Task 4: Implement Confirmed Segmented Feed and Retract Calibration

**Files:**
- Modify: `tests/test_ace_driver_calibration.py`
- Modify: `extras/ace.py`

- [ ] **Step 1: Add failing command and segmentation tests**

```python
def test_calibrate_feed_without_confirm_only_previews(self):
    ace, gcmd = make_calibration_command(confirm=0)
    ace.cmd_ACE_CALIBRATE_FEED(gcmd)
    self.assertEqual(ace.motion_calls, [])

def test_calibrate_feed_counts_completed_chunks_and_upper_bound(self):
    ace = make_calibration_ace(sensor_sequence=[False, False, True])
    preview = ace._calibrate_feed(index=0)
    self.assertEqual(ace.feed_lengths, [5.0, 5.0])
    self.assertEqual(preview['completed_distance'], 5.0)
    self.assertEqual(preview['upper_bound_distance'], 10.0)

def test_disconnect_discards_preview_and_never_replays_chunk(self):
    ace = make_calibration_ace(disconnect_on_call=2)
    with self.assertRaises(Exception):
        ace._calibrate_feed(index=0)
    self.assertIsNone(ace._calibration_preview)
    self.assertEqual(ace.feed_lengths, [5.0, 5.0])
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m unittest tests.test_ace_driver_calibration -v`  
Expected: FAIL because calibration commands are not registered.

- [ ] **Step 3: Implement idle preflight and motion mutex**

```python
def _require_idle_calibration_state(self):
    state = self._print_state()
    if state in ('printing', 'paused'):
        raise self.printer.command_error('ACE：打印或暂停期间禁止标定')
    if self._sensor_present('extruder_sensor') or self._sensor_present('toolhead_sensor'):
        raise self.printer.command_error('ACE：标定前上下传感器必须均无料')
```

Use one `_motion_owner` value for toolchange, endless spool, preload, calibration and manual movement.

- [ ] **Step 4: Implement segmented calibration commands**

Register `ACE_CALIBRATE_FEED`, `ACE_CALIBRATE_RETRACT`, `ACE_CALIBRATION_SAVE`, and `ACE_CALIBRATION_CANCEL`. Require `CONFIRM=1` for movement and save; without it, report a Chinese preview only.

Feed with `calibration_chunk_length`; retract with the same chunk and use `calibration_final_chunk_length` over the final 20 mm. Check debounced sensors before and after every segment.

- [ ] **Step 5: Implement failure semantics**

On disconnect, timeout or contradictory sensors: request protocol stop when connected, set the involved slot to `unknown`, discard only the current preview, and call `PAUSE` only when `_print_state() == 'printing'`.

- [ ] **Step 6: Run calibration and full Python tests**

Run: `python -m unittest discover -s tests -p "test_*.py" -v`  
Expected: all tests PASS.

- [ ] **Step 7: Commit calibration state machine**

```bash
git add extras/ace.py tests/test_ace_driver_calibration.py
git commit -m "feat: calibrate ACE feed and retract distances"
```

### Task 5: Add Safe Cold Preload and Clear-Path Handling

**Files:**
- Modify: `tests/test_ace_driver_calibration.py`
- Modify: `extras/ace.py`
- Modify: `ace.cfg`

- [ ] **Step 1: Add failing preload safety tests**

```python
def test_preload_without_confirm_never_moves(self):
    ace, gcmd = make_preload_ace(confirm=0, upper=False, lower=False)
    ace.cmd_ACE_PRELOAD(gcmd)
    self.assertEqual(ace.motion_calls, [])

def test_preload_rejects_lower_sensor_with_unknown_position(self):
    ace, gcmd = make_preload_ace(confirm=1, lower=True,
                                 position='unknown')
    with self.assertRaises(Exception):
        ace.cmd_ACE_PRELOAD(gcmd)

def test_cold_preload_stops_on_lower_sensor_without_nozzle_distance(self):
    ace, gcmd = make_preload_ace(confirm=1,
                                 lower_sequence=[False, False, True])
    ace.cmd_ACE_PRELOAD(gcmd)
    self.assertEqual(ace.cold_extruder_steps, [5.0, 5.0])
    self.assertNotIn(ace.toolhead_sensor_to_nozzle_length,
                     ace.cold_extruder_steps)
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m unittest tests.test_ace_driver_calibration -v`  
Expected: FAIL because `ACE_PRELOAD` does not exist.

- [ ] **Step 3: Implement explicit `ACE_PRELOAD` command**

Do not infer preload from `print_stats`; `ACE_CHANGE_TOOL` and T0-T3 retain full nozzle-loading semantics. `ACE_PRELOAD INDEX=n CONFIRM=1` checks idle state, slot identity, saved position and both sensors.

- [ ] **Step 4: Implement bounded cold extruder movement**

Use a dedicated internal helper that invokes controlled `FORCE_MOVE STEPPER=extruder` segments, with total distance capped by `toolhead_sensor_max_feed_length`. Use existing fast/slow step parameters, test the lower sensor after every segment, and never append `toolhead_sensor_to_nozzle`.

After movement, call the existing Klipper position resynchronization path and save the selected slot as `toolhead`.

- [ ] **Step 5: Split macro entry behavior**

Keep `_ACE_PRE_TOOLCHANGE` and `_ACE_POST_TOOLCHANGE` for full nozzle loads only. `ACE_PRELOAD` must not call G28, XY/Z moves, cutter, cleaner or heater commands.

- [ ] **Step 6: Run tests and inspect generated command traces**

Run: `python -m unittest tests.test_ace_driver_calibration -v`  
Expected: PASS with no heater/XY/cutter command in preload traces.

- [ ] **Step 7: Commit cold preload**

```bash
git add ace.cfg extras/ace.py tests/test_ace_driver_calibration.py
git commit -m "feat: add confirmed cold ACE preload"
```

### Task 6: Integrate Estimated Parking into Normal Toolchanges

**Files:**
- Modify: `tests/test_ace_driver_calibration.py`
- Modify: `extras/ace.py`

- [ ] **Step 1: Add failing toolchange transition tests**

```python
def test_same_tool_at_toolhead_completes_heated_nozzle_load(self):
    ace = make_toolchange_ace(current=0, slot_position='toolhead')
    ace.change_tool(0)
    self.assertEqual(ace.macro_calls, ['_ACE_PRE_TOOLCHANGE',
                                       '_ACE_POST_TOOLCHANGE'])
    self.assertEqual(ace.slot_positions[0], 'nozzle')

def test_old_tool_parks_and_new_tool_loads_from_estimated_position(self):
    ace = make_toolchange_ace(current=0, target=1,
                              positions=['nozzle',
                                         'preload_parked_estimated',
                                         'unknown', 'unknown'])
    ace.change_tool(1)
    self.assertEqual(ace.slot_positions[0], 'preload_parked_estimated')
    self.assertEqual(ace.slot_positions[1], 'nozzle')
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m unittest tests.test_ace_driver_calibration -v`  
Expected: FAIL because same-tool returns early and unload always uses `toolchange_retract_length`.

- [ ] **Step 3: Implement state-based same-tool behavior**

Only return early when the requested slot is already `nozzle` and sensor state agrees. A `toolhead` slot must run the heated remainder-to-nozzle path.

- [ ] **Step 4: Implement parking and fallback paths**

Use valid calibration for `preload_parked_estimated`; use complete sensor-protected loading for `unknown` or expired calibration. On unload, park the old slot using the calibration distance and preserve its slot identity.

- [ ] **Step 5: Harden cutter decision**

Run `CUT_TIP` only when lower sensor and state indicate nozzle occupancy and the recovery phase has not already completed cutting. A contradictory saved state must become `unknown`, not silently skip required recovery.

- [ ] **Step 6: Run all driver tests**

Run: `python -m unittest discover -s tests -p "test_ace_driver*.py" -v`  
Expected: PASS.

- [ ] **Step 7: Commit toolchange integration**

```bash
git add extras/ace.py tests/test_ace_driver_calibration.py
git commit -m "feat: park ACE slots between toolchanges"
```

### Task 7: Fix Cancellation, Endless Spool and Moonraker Contract

**Files:**
- Modify: `tests/test_ace_driver_calibration.py`
- Modify: `tests/test_ace_status_component.py`
- Modify: `extras/ace.py`
- Modify: `ace_status_integration/moonraker/ace_status.py`

- [ ] **Step 1: Add failing safety and contract tests**

```python
def test_endless_spool_does_not_act_while_standby(self):
    ace = make_endless_ace(print_state='standby', runout_samples=[True] * 5)
    ace._endless_spool_monitor(0.0)
    self.assertEqual(ace.toolchange_calls, [])

def test_abort_requests_real_protocol_stop(self):
    ace = make_active_motion_ace(method='feed_filament')
    ace.cmd_ACE_ABORT_TOOLCHANGE(make_confirmed_gcmd())
    self.assertEqual(ace.stop_calls, [('feed', ace.active_index)])

def test_capabilities_do_not_advertise_unregistered_ack(self):
    self.assertNotIn('ACE_ACK_TOOLCHANGE', ace_status.COMMAND_BUILDERS)
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m unittest tests.test_ace_driver_calibration tests.test_ace_status_component -v`  
Expected: FAIL for standby endless spool, marker-only stop, and ACK mismatch.

- [ ] **Step 3: Implement print-only endless-spool debounce**

Require `print_stats == printing` and N stable runout samples before changing slots. Reset debounce outside printing and while any motion owner is active.

- [ ] **Step 4: Implement real abort**

Track active ACE method and slot. Abort sends `stop_feed_filament` or `stop_unwind_filament`, disables feed assist, marks uncertain slot positions `unknown`, and leaves a printing job paused.

- [ ] **Step 5: Align Moonraker commands**

Remove `ACE_ACK_TOOLCHANGE` unless a matching driver command is implemented. Add strict builders for preload, calibration, save/cancel and full unload. Require `CONFIRM=1`; block calibration/preload/full-unload while printing.

- [ ] **Step 6: Run Python tests**

Run: `python -m unittest discover -s tests -p "test_*.py" -v`  
Expected: all PASS.

- [ ] **Step 7: Commit safety contract fixes**

```bash
git add extras/ace.py ace_status_integration/moonraker/ace_status.py tests/test_ace_driver_calibration.py tests/test_ace_status_component.py
git commit -m "fix: align ACE safety controls and API"
```

### Task 8: Add Normalized Calibration State to Frontend Contract

**Files:**
- Modify: `tests/test_ace_status_component.py`
- Modify: `ace_status_integration/moonraker/ace_status.py`
- Modify: `fluidd-source-overlay/src/types/acePro.ts`
- Modify: `fluidd-source-overlay/src/util/acepro.ts`
- Modify: `fluidd-source-overlay/src/util/acepro.test.ts`
- Mirror: corresponding files under `../fluidd-develop/src/`

- [ ] **Step 1: Add failing normalization tests**

```python
self.assertEqual(status['slot_positions'][0], 'preload_parked_estimated')
self.assertTrue(status['calibration']['valid'])
self.assertEqual(status['calibration']['feed_upper_bound'], 1205)
self.assertEqual(status['calibration']['parking_distance'], 1035)
```

```typescript
expect(state.calibration.valid).toBe(true)
expect(state.slotPositions).toEqual([
  'preload_parked_estimated', 'unknown', 'unknown', 'unknown',
])
```

- [ ] **Step 2: Run Python and Fluidd unit tests and confirm failure**

Run: `python -m unittest tests.test_ace_status_component -v`  
Expected: FAIL.  
Run in `../fluidd-develop`: `pnpm.cmd test:unit --run src/util/acepro.test.ts`  
Expected: FAIL.

- [ ] **Step 3: Normalize a stable API shape**

```typescript
export interface AceProCalibrationState {
  available: boolean
  valid: boolean
  stale: boolean
  phase: string
  selectedSlot: number
  feedCompleted: number
  feedUpperBound: number
  retractDistance: number
  parkingDistance: number
  lastError: string
}
```

Normalize missing older-driver fields to safe unavailable/default values.

- [ ] **Step 4: Sync the tested source files to the overlay**

Use file comparison before copying; overlay and development tree must be byte-identical for the changed ACE files.

- [ ] **Step 5: Run normalization tests**

Run: `python -m unittest tests.test_ace_status_component -v`  
Expected: PASS.  
Run in `../fluidd-develop`: `pnpm.cmd test:unit --run src/util/acepro.test.ts`  
Expected: PASS.

- [ ] **Step 6: Commit frontend contract**

```bash
git add ace_status_integration/moonraker/ace_status.py tests/test_ace_status_component.py fluidd-source-overlay/src/types/acePro.ts fluidd-source-overlay/src/util/acepro.ts fluidd-source-overlay/src/util/acepro.test.ts
git commit -m "feat: expose ACE calibration status"
```

### Task 9: Build Matching Fluidd and Standalone Calibration UI

**Files:**
- Modify: `fluidd-source-overlay/src/mixins/acePro.ts`
- Modify: `fluidd-source-overlay/src/components/widgets/acepro/AceProCard.vue`
- Modify: `fluidd-source-overlay/src/views/AcePro.vue`
- Modify: `tests/web/fluidd-card-layout.test.mjs`
- Modify: `ace_status_integration/web/ace-dashboard.js`
- Modify: `ace_status_integration/web/ace-dashboard.css`
- Modify: `ace_status_integration/web/ace.html`
- Create: `tests/web/calibration-page.test.mjs`
- Mirror: corresponding Fluidd files under `../fluidd-develop/src/`

- [ ] **Step 1: Add failing required-control and command tests**

Assert both interfaces contain Chinese labels for `距离标定`, `冷态预装载`, `送料结果`, `回料结果`, `保存标定`, and `紧急停止`; assert preload sends `ACE_PRELOAD` and slot primary action still sends `ACE_CHANGE_TOOL`.

```javascript
assert.match(cardSource, /ACE_PRELOAD/)
assert.match(cardSource, /ACE_CHANGE_TOOL/)
assert.match(pageSource, /距离标定/)
```

- [ ] **Step 2: Run web tests and confirm failure**

Run: `node --test tests/web/*.test.mjs`  
Expected: FAIL because calibration controls do not exist.

- [ ] **Step 3: Implement shared interaction behavior**

Add methods that show a confirmation dialog and immediately send one whitelisted command. Never retain a reusable confirmation flag. Disable motion controls while printing, disconnected, another motion is active, or required sensors/state are unsafe.

- [ ] **Step 4: Implement compact Fluidd wizard**

Use one un-nested calibration section with current phase, two sensor switches, distance result rows and context-specific actions. Keep the card width unchanged and ensure controls wrap without increasing slot-card width.

- [ ] **Step 5: Implement full-size `/ace.html` equivalent**

Use the same state labels, commands, confirmation text, failure text and button availability. Difference is layout density only.

- [ ] **Step 6: Run web and Fluidd tests**

Run: `node --test tests/web/*.test.mjs`  
Expected: PASS.  
Run in `../fluidd-develop`: `pnpm.cmd typecheck && pnpm.cmd lint && pnpm.cmd test:unit --run`  
Expected: all PASS.

- [ ] **Step 7: Commit interface implementation**

```bash
git add fluidd-source-overlay/src ace_status_integration/web tests/web
git commit -m "feat: control ACE calibration from Fluidd"
```

### Task 10: Document Configuration and Upgrade Behavior

**Files:**
- Modify: `ace.cfg`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/DRIVER-v1.1.0.zh-CN.md`
- Modify: `tests/test_release_docs.py`

- [ ] **Step 1: Add failing documentation assertions**

```python
for term in (
        'bowden_tube_length', 'ACE_PRELOAD',
        'ACE_CALIBRATE_FEED', 'preload_parked_estimated',
        '普通 T0-T3 始终送入喷嘴'):
    self.assertIn(term, readme)
```

- [ ] **Step 2: Run documentation tests and confirm failure**

Run: `python -m unittest tests.test_release_docs -v`  
Expected: FAIL for missing workflow and parameter text.

- [ ] **Step 3: Update Chinese comments and instructions**

Correct `bowden_tube_length` to “ACE 出料口到五通进料口”. Add calibration parameters, prerequisite sensor states, confirmation steps, cold-preload limitations, approximate parking limitation, failure recovery and re-calibration triggers.

- [ ] **Step 4: Add upgrade and rollback notes**

Document legacy position migration, older Fluidd behavior, stale calibration fallback, and that installation backups remain rollback sources. Do not claim GitHub release or publish a version in this task.

- [ ] **Step 5: Run docs tests**

Run: `python -m unittest tests.test_release_docs -v`  
Expected: PASS.

- [ ] **Step 6: Commit documentation**

```bash
git add ace.cfg README.md CHANGELOG.md docs/DRIVER-v1.1.0.zh-CN.md tests/test_release_docs.py
git commit -m "docs: explain ACE calibration and preload"
```

### Task 11: Build, Package and Verify Offline

**Files:**
- Replace: `fluidd-dist/**` with one clean build from `../fluidd-develop`
- Modify: `manifest.sha256`

- [ ] **Step 1: Run the complete pre-build suite**

Run: `python -m unittest discover -s tests -p "test_*.py" -v`  
Expected: all PASS.  
Run: `node --test tests/web/*.test.mjs`  
Expected: all PASS.

- [ ] **Step 2: Build Fluidd from the verified development tree**

Run in `../fluidd-develop`: `pnpm.cmd typecheck && pnpm.cmd lint && pnpm.cmd test:unit --run && pnpm.cmd build`  
Expected: all commands exit 0 and `dist/index.html` references only current hashed assets.

- [ ] **Step 3: Replace release assets without retaining stale chunks**

Move the existing local `fluidd-dist` to a timestamped directory under repository `.temporary/`, copy the complete new `dist`, then verify every asset referenced by `index.html` and `sw.js` exists.

- [ ] **Step 4: Run installer regression suite**

Run in a Bash environment:

```bash
bash -n install.sh uninstall.sh ui-installer.sh
bash tests/installer/test-installer.sh
bash tests/installer/test-install-scopes.sh
bash tests/installer/test-install-failure.sh
```

Expected: syntax and all install/rollback scenarios PASS.

- [ ] **Step 5: Regenerate and verify manifest**

Generate SHA-256 entries for the exact release tree, excluding `.git`, `.temporary`, local caches and backup directories. Re-read every entry and require zero missing or mismatched files.

- [ ] **Step 6: Commit the verified build**

```bash
git add fluidd-dist manifest.sha256
git commit -m "build: package ACE calibration interface"
```

### Task 12: Deploy Safely to the Printer

**Files:**
- Remote: ACE driver symlink target, `printer_data/config/ace.cfg`, Moonraker component, standalone web files, Fluidd distribution.
- Local backup tool: `../printer-tools/Backup-PrinterConfig.ps1`

- [ ] **Step 1: Read printer state without backup**

Query Moonraker `print_stats`, Klipper state, ACE connection, current sensors, active toolchange and service status. Expected: printer is not `printing` or `paused`; otherwise stop deployment.

- [ ] **Step 2: Create the mandatory before-change backup**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Luomo\Documents\ace profluidd上的可视化界面\printer-tools\Backup-PrinterConfig.ps1" -Label before-change -Reason "变更前：安装距离标定、五通预停放和冷态预装载功能，计划更新 ACE 驱动、配置、Moonraker 组件及 Fluidd 文件，并保留完整回滚来源。"
```

Expected: a new timestamped directory under `C:\Users\Luomo\桌面\打印机配置备份` containing `备份说明.txt`, `backup-manifest.json` and verified `SHA256SUMS`. If this fails, stop without remote writes.

- [ ] **Step 3: Upload atomically and preserve current remote files**

Upload to timestamped temporary paths, verify SHA-256 on the printer, then replace only the intended files. Preserve installer rollback copies and do not delete historical backups.

- [ ] **Step 4: Perform static and service validation**

Run Python compilation on uploaded components, verify config includes and symlink targets, restart only after rechecking `print_stats`, then confirm Klipper and Moonraker active, ACE connected, status endpoint available and Fluidd index/assets return HTTP 200.

- [ ] **Step 5: Do not trigger physical validation automatically**

Report the staged manual sequence: inspect sensors, preview calibration, confirm feed calibration, inspect result, confirm retract calibration, save, then test `ACE_PRELOAD` with the user present. Do not send T0-T3, feed, retract or cutter commands during installation verification.

- [ ] **Step 6: Create the mandatory after-change backup**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Luomo\Documents\ace profluidd上的可视化界面\printer-tools\Backup-PrinterConfig.ps1" -Label after-change -Reason "变更后：已更新 ACE 距离标定、每槽预停放、冷态预装载、Moonraker 接口和 Fluidd 控制界面，并完成语法、服务、API、静态资源及文件哈希验证，未自动触发物理动作。"
```

Expected: a second verified backup directory. Final report must list both backup paths, reasons, service/API results and unperformed physical tests.

## Final Verification

- [ ] `python -m unittest discover -s tests -p "test_*.py" -v` passes.
- [ ] `node --test tests/web/*.test.mjs` passes.
- [ ] Fluidd typecheck, lint, full unit suite and production build pass.
- [ ] Installer install, force-install, driver-only, card-only, rollback and failure recovery pass.
- [ ] Release manifest has zero missing or mismatched entries.
- [ ] Printer before-change and after-change backups both exist and verify.
- [ ] Klipper and Moonraker are active, ACE is connected, and Fluidd assets load.
- [ ] No physical motion was triggered without the user's explicit confirmation.
- [ ] No GitHub push, tag or release was created.
