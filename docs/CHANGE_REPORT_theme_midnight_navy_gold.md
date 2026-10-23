# Change report: Midnight Navy + Gold theme (on v2.1.2)

Scope: visual theme only. No markup, class names, layout, routes, API, permissions, translations or business logic were changed.
The existing theme system was updated in place: tokens in `frontend/src/styles.css`, mode switching in `src/theme/ThemeContext.tsx` (unchanged apart from the `theme-color` value).

## Files changed
| File | Why |
|---|---|
| `frontend/src/styles.css` | Token blocks replaced (light, dark-by-OS-preference, dark-by-toggle); component rules re-pointed at the new tokens; hover states and `.gold` button added. All selectors and every layout property are unchanged. |
| `frontend/src/theme/ThemeContext.tsx` | `theme-color` meta now `#14263D` (the topbar is Midnight Navy in both themes). |
| `frontend/index.html` | Initial `theme-color` `#14263D` (was olive). |
| `frontend/public/favicon.svg` | Olive tile and bright-gold shield recoloured to `#14263D` / `#C6A15B`. |
| `CHANGELOG.md`, this report | Documentation. |

All other files, including every `.tsx` page and component, tests, i18n, backend, ops, CI and `package*.json`, are unchanged. Version numbers are unchanged.

## Token model
Brand (theme-independent): `--navy #14263D`, `--navy-2 #203B56`, `--navy-deep #0D1522`, `--gold #C6A15B`, `--gold-light #E2CC98`.
Theme tokens keep their v2.1.2 role names (`--mist` page, `--paper` card, `--ink` text, `--slate` secondary text, `--line` divider; `--amber` warning, `--brick` error, `--ok` success) and reference the brand tokens where they are brand colours.
`--pine` and `--pine-dark` were removed (nothing outside `styles.css` referenced them).

| Token | Light | Dark |
|---|---|---|
| `--mist` / `--paper` / `--surface-2` | #F4F6F9 / #FFFFFF / #EAF0F6 | #0D1522 / #162235 / #1B2B40 |
| `--ink` / `--slate` / `--line` | #1D2939 / #667085 / #D9E0E8 | #F3F6FA / #AAB7C7 / #2B3A4D |
| `--control-border` (new) | #7B8AA0 | #60758F |
| `--accent-text` | #203B56 | #E2CC98 |
| `--gold-strong`, `--focus` (new) | #8A6A1F | #C6A15B |
| `--brand` / `--brand-hover` / `--brand-border` (new) | #14263D / #203B56 / #14263D | #14263D / #203B56 / #C6A15B |
| `--chrome` (topbar, nav), `--nav-active` (new) | #14263D, #203B56 | same |
| `--ok` / `--ok-bg` | #247547 / #E4F2EA | #6FD39B / #123524 |
| `--amber` / `--amber-bg` (warning) | #946200 / #FBF0D6 | #F0B04A / #3A2A0B |
| `--brick` / `--brick-bg` (error) | #B42318 / #FCE9E7 | #FF8E83 / #451F1B |
| `--info` / `--info-bg` (new) | #245EA8 / #E5EEF9 | #85B8F2 / #142F4E |
| `--chart-1`, `--meter-from`, `--meter-to` (new) | #203B56, #203B56, #A8832F | #C6A15B, #5B86B5, #C6A15B |

## Deliberate differences from the brief, and why
1. **Muted Gold is not used for text or functional graphics on light surfaces.** `#C6A15B` on white is 2.43:1. Functional gold on light (focus ring, active step, drop-zone highlight) uses `--gold-strong #8A6A1F` (5.05:1). Muted Gold remains for decorative accents, on navy chrome (6.29:1) and throughout dark mode (6.58:1).
2. **Secondary text `#667085` is kept exactly**, but it is 4.33:1 on the subtle surface `#EAF0F6`. Muted text must therefore not be placed on `--surface-2` (used for chips, table header, secondary-button hover); alternating table rows use `#F4F6F9` (4.59:1).
3. **Input and secondary-button borders use `--control-border`** (3.5:1 light, 3.4:1 dark) instead of `--line` (1.33:1), to meet WCAG 1.4.11. `--line` stays for decorative dividers.
4. **Dark-mode primary buttons have a gold border**: Midnight Navy on a dark card is 1.05:1, so the border is what makes the button visible. Hover is Secondary Navy in both themes.
5. **`.notice.info` is now the Informational blue** (it was amber). Default notices in the app are neutral/positive messages, not warnings. Warning (amber) styling is unchanged for chips, KPIs and the attention panel.
6. **The Analytics bar is now `--chart-1`** (navy / gold) instead of success green, so it no longer reads as a "success" status.
7. **Dark-mode danger button text is white on `#B42318`** (6.57:1). Previously one token served as both text and fill, which gave white on light red in dark mode.
8. New, additive: hover states (none existed), `thead` and alternating-row backgrounds, placeholder colour, checkbox/radio `accent-color`, opt-in `.gold` button (defined; **not applied to any existing button**), `--chart-2` (reserved; no multi-series chart exists yet).

## Verification actually performed
Environment: Chromium 141 (Playwright), Python WCAG calculator, TypeScript 6.0.3 (global). Method: a static harness that uses the **real `styles.css`** with the app's real class names and Somali strings (Layout, Dashboard, ui.tsx, Personnel, Analytics, OrgTree patterns). It is not the React app.

| Check | Result |
|---|---|
| Token audit: dark blocks (OS preference vs toggle) identical; no undefined `var()`; no unused tokens; no olive values left in `styles.css` | passed |
| 427 CSS declarations accepted by Chromium's parser | passed (0 rejected) |
| Text contrast, 129 text nodes x light/dark x desktop 1280 / tablet 820 / phone 360, plus OS-dark with no `data-theme` | **0 failures**; minimum 4.59:1 (light), 6.29:1 (dark) |
| Hover text contrast (9 controls x 2 themes) | 8.66:1 to 12.43:1 |
| Keyboard focus ring vs surrounding surface (9 controls x 2 themes) | 4.54:1 to 9.69:1 (need 3:1) |
| Input / select / secondary-button boundary | 3.51:1 light, 3.38:1 dark (need 3:1) |
| Element geometry, original CSS vs new CSS (229 elements x 3 sizes x 2 themes) | **0 differences** (no layout change) |
| Element geometry, light vs dark | 0 differences (no layout shift on toggle) |
| Horizontal overflow at 360px | none |
| Syntax of the one changed `.tsx` file | 0 diagnostics before and after |
| Screenshots reviewed by eye: desktop, tablet and phone, light and dark | reviewed |

## NOT run (the authoring sandbox cannot reach the npm registry, so dependencies could not be installed)
- `npm run typecheck`, `npm run build`, `npm run build:demo`, `npm run lint`, `npm test` (vitest), and the Playwright e2e/axe suite: **not executed**. The only TypeScript change is a string literal; the unit tests do not touch theme code; but none of this is a substitute for running them. Please run `npm ci && npm run typecheck && npm run lint && npm test && npm run build` before release.
- The real React app was not rendered. Pages and states that the harness does not reproduce (every individual page, loading/error states, org-tree depth, PDF export) were not visually checked.
- Real Android device, Safari/Firefox, assistive technology, print output: not tested.
- Backend, API, authentication, permissions, workflows: not touched, so not re-tested.
- `docs/TEST_PLAN_1.4.md` still lists contrast as NOT RUN; it was left unchanged, since only a run against the real build should update it.

## Remaining issues / things to watch
- Warning amber (`#946200` / `#F0B04A`) and brand gold are the same hue family. They differ in saturation and are always accompanied by text or an icon, but side-by-side they are close; a reviewer should confirm this is acceptable.
- In dark mode the sidebar (`#14263D`) is only slightly lighter than cards (`#162235`). They do not touch, so separation is carried by the page background and the 1px chrome border.
- Disabled controls keep the existing 55% opacity and are exempt from contrast requirements.
