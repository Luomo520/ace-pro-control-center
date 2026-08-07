# Third-Party Notices

Ace Pro Control Center is licensed under the GNU General Public License version 3. It
is a general Klipper reimplementation informed by the following GPL-3.0
projects. Their printer-specific configurations, pins, coordinates, and macros
are not distributed as V3 defaults.

## Kobra-S1/ACEPRO

- Source: https://github.com/Kobra-S1/ACEPRO
- Reviewed commit: `221f27b92f2eee39e3b8eacf7c3c3b198237b972`
- License: GNU General Public License version 3
- Use in V3: architecture of the multi-instance manager, protocol adapters,
  serial supervision, ACE2 bus identity, persistence, and associated tests.
  V3 rewrites integration for generic Klipper and configured logical ordering.

The upstream copyright notices remain applicable to portions derived from or
adapted from that project.

## szkrisz/ACEPROSV08

- Source: https://github.com/szkrisz/ACEPROSV08
- Reviewed commit: `0311eb375cb7f14d41a8e2029d4a6d7363c6ceba`
- License: GNU General Public License version 3
- Use in V3: ACE1 frame and action behavior cross-checks plus the familiar
  four-row ACE user-interface behavior. SV08-specific pins, coordinates,
  cutter motions, temperatures, and macros are excluded.

The upstream copyright notices remain applicable to portions derived from or
adapted from that project.

## moggieuk/Happy-Hare

- Source: https://github.com/moggieuk/Happy-Hare
- Reviewed commit: `73d39aab2110deebb64dfb7899c6838a706edcea`
- License: GNU General Public License version 3
- Use in V3: visual information hierarchy of `config/base/mmu_parameters.cfg`
  and the encoder mechanism described by `extras/mmu_encoder.py` and the
  related hardware, parameter, and calibration configuration. V3 adapts only
  generic pulse counting, millimetres-per-pulse calibration, and movement
  detection for one shared encoder on the common filament path.
- Excluded from V3: Happy Hare selectors, gear steppers, MMU toolheads,
  automatic feed compensation, Spoolman integration, MMU recovery, printer
  pins, and machine-specific motion values. The V3 encoder does not replace a
  filament-presence switch and does not command additional feed movement.

The upstream copyright notices remain applicable to portions derived from or
adapted from that project.

## Distribution obligations

Redistributions of Ace Pro Control Center, modified or unmodified, must comply with
GPL-3.0. Source code, this notice, the license text, and notices retained in
individual source files must remain available as required by that license.
