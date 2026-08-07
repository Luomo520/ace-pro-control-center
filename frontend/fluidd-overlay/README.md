# Ace Pro Control Center Fluidd overlay

The overlay is a Vue 2/Vuetify integration for Fluidd source builds. It adds
the ACE card to Dashboard and installs a native `/acepro` page reachable from
the `ACE Pro` sidebar item. The page reuses `AceV3Card` in page mode: its page
link is hidden and its diagnostics section is enabled.

The card directly follows the V2 Fluidd hierarchy and visual styling: header,
device/dryer status, four compact spool cards, manual feed, and quick actions.
Only these real V2 screenshots are visual acceptance references:

- `Ace-Pro-Control-Center-V2/docs/images/acepro-fluidd-dashboard-overview.png`
- `Ace-Pro-Control-Center-V2/docs/images/acepro-fluidd-card-detail.png`

`Ace-Pro-Control-Center-V2/docs/images/fluidd-acepro-card.png` is an invalid
early example and must not be used for layout or release review. A device
switch is inserted only when two to four ACE devices are configured; hidden
device slot components stay mounted so unsaved inventory drafts survive a
device switch.

The card imports `./ace-core.js`. The installer links that path directly to the
framework-independent `frontend/shared/ace-core.js`, so both frontends execute
the same implementation. The stable exports
are `normalizeAceState`, `buildViewModel`, `canPerformAction`, and
`AceApiClient`.

The card only accesses `GET /server/ace/status` and
`POST /server/ace/action`. It never constructs or submits G-code.

Passing `--fluidd-source` makes the installer patch these Fluidd files:

- `src/views/Dashboard.vue`
- `src/store/layout/state.ts`
- `src/router/index.ts`
- `src/components/layout/AppNavDrawer.vue`
- `src/components/widgets/toolhead/ToolChangeCommands.vue`

All five files participate in the same installation transaction. Patches are
anchor-checked and idempotent. The router and navigation patcher can take over
the exact V2 `/acepro` route and `ACE Pro` item; any other same-name route or
navigation item is rejected as an unmanaged conflict before files are written.
When Klipper exposes a valid `ace.device_count`, Fluidd's tool controls show
only `device_count * 4` tool commands in one four-column row per ACE. If the
ACE status object is absent or invalid, the upstream Fluidd grouping is left
unchanged.
Uninstall removes only V3-marked source and restores overlay files that the
installer replaced. Fluidd must then be rebuilt and its generated `dist`
deployed.
