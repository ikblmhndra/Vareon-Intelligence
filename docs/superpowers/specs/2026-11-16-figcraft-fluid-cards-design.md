# FigCraft redesign: components fill their cards (0.8.16)

Status: approved 2026-11-16. Follow-up to `2026-11-15-figcraft-ui-audit-fixes-design.md`; ships in PR #91, no version bump.

## Intent

After the shell went full width (up to 1920 px), dev showed components that keep a fixed size inside wider cards:
the Analyst board Sector heatmap fills about 40 % of its card, the Dashboard Lead story stops short of its row and
leaves an empty band below it, and the Needs-action map stays 500 × 380 px. The user asked that sizes be relative:
each component fills the width and height of its card (user choice "isi lebar & tinggi kartu"). Text size and
spacing stay as they are (fluid type was offered and not chosen).

## Approaches

- **Per component, fill the container (picked):** heat cells stretch to equal column widths, focus cards stretch to
  the row and push their footer down, the map and charts size from their box. Small, targeted, no global effect.
- Global scale with screen width (clamp/vw on type and spacing): not chosen by the user.

## Design

1. **HeatGrid** (`components/ui/heat-grid.tsx`, used by Risk matrix, MITRE heatmap, Exec Sector heatmap): the table
   takes the full card width; value columns share the remaining width equally (row-label column sized to its text);
   cells fill their column (keep `min-w-10`, height stays 40 px). Keyboard navigation, sticky headers and the inner
   scroll at narrow widths stay. Builder call: no max cell width.
2. **Focus cards** (Dashboard Lead story, Newsroom Top story, Exec Threat actors): stretch to the row height again,
   with content laid out as a column whose last block (Lead story "Why it ranks first", Top story ranking line,
   Threat actors "Show all") sits at the bottom (`mt-auto`). The summary shows more lines when the card is taller
   (Lead/Top story clamp raised to fit, full summary when it fits). Threat actors keeps its 5-row collapsed list.
   This replaces the `self-start` from the audit fix; spec §4's "no large empty interior" still holds because the
   footer block, not empty space, takes the bottom.
3. **Needs-action map** (`components/dashboard/needs-action.tsx`): the right column becomes proportional
   (`minmax(0,3fr)_minmax(0,2fr)` or similar) and the map box is `w-full` with a fixed aspect ratio (500:380)
   instead of 500 × 380 px. `WorldDots` already resizes with its box (ResizeObserver).
4. **Charts in rows** (`ChartCard` in `components/dashboard/stat-box.tsx`, Dashboard month charts, Exec chart cards):
   the chart body grows to fill the card when a neighbour makes the row taller; today's `height` becomes the
   minimum height. No chart gets shorter than today.

## Non-goals

Font sizes, spacing, mobile (<1024), tables' column logic, backend.

## Verification

lint + typecheck + build; local browser at ≥1920, 1440 and 1024, light and dark: Sector heatmap fills its card, no
empty band under Lead story, map scales, charts not squashed, no page scroll at 1024; then dev after deploy.
