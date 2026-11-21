# Harvest visual system

## Direction

Operate register: standard side navigation, a readable work area and familiar forms. Inspiration comes from produce labels and agricultural field records, expressed only through typography, color, density and explicit provenance labels. Keep setup, current readings and human inspection equally accessible.

## Tokens

Warm paper ground #f6f7f1; white panels; forest #163f32; leaf #d0e59c; ink #202c25; secondary text #596458; lines #dce2d7. Risk state colors support text labels: low risk green, elevated amber, high risk brick, insufficient evidence slate. Simulation uses a written violet label. All data series have labelled legends and distinct line treatments.

## Typography

Self-hosted DM Sans for interface and display, with system fallbacks. Tabular numerals in readings. Clear 14/16px supporting/body text, 20px panel headings and 32px screen headings. Public hero is larger, with balanced lines and short copy.

## Layout and components

240px forest sidebar; 32px desktop content gutters; 16px on phones; 12px bordered panel radii. Quiet panel headings, plain tables and compact status chips. Overview splits inspection and setup, followed by actual latest readings. Dialogs use native focus management for record creation and protected credential display. Inline errors and retry controls retain stale cached records honestly.

## Interaction and accessibility

44px primary targets; visible keyboard focus, labelled inputs, skip links, semantic navigation and tables. Mobile navigation is collapsible, tables scroll within their own region and forms become a single column. Low motion; reduced-motion preference disables transitions/spinners. Observation, model and sensor strings render as text. Charts have an accessible reading table.

## Surfaces

Landing: product explanation, semantic workflow diagram and capabilities; no fabricated metrics or data. Login: two-column narrative and a focussed form, collapsing on phones. Operational views: scanability, uncertainty, provenance and timestamps before decoration.

## Design skill (installed 2026-11-21 with the user's approval)

- **Skill:** `design-taste-frontend` (taste-skill 2.5.1, MIT), from <https://github.com/Leonxlnx/taste-skill>, commit `f6b76575f949707b4e3c37cd86cb44b0b98643e8`.
- **How:** the repo was cloned to a temporary folder, its scripts were read (they only start a local headless Chrome and fetch fonts, icons and open-archive photographs), and `skills/taste-skill/` was copied to `.kiro/skills/design-taste-frontend/` together with its `LICENSE`. The `npx skills` CLI was not used. Nothing was installed globally. The folder is git-ignored; reinstall by copying it again from that commit.
- **Needs:** Node 22+ and Chrome/Edge/Chromium (present); ffmpeg is optional. No API keys.
- **Scope:** public pages (landing, login, signup) follow the skill in full, including real photographs credited in one footer line. Authenticated operating screens use only its tokens, typography, spacing and checks. Per `agent.md`, accessibility, status and safety rules come first, motion in monitoring views stays low, and simulated data keeps its written violet label (a status, not a design accent).
