# Permanent rule: everything that is opened or filtered has its own URL (web console)

Every agent that creates or changes a console screen (`scripts/engine/ui/static/js/`) must read this rule.

## Principle

Navigation state lives in the URL, not only in `useState`. Copying the address from the bar and opening it in
another tab (or after F5) must reproduce exactly the same screen.

## Rules

1. **Every menu = one URL.** Each sidebar item is `#<menu>` (e.g.: `#hosts`, `#backups`, `#memory`).
2. **Every opened item = a distinct URL**, in any menu: host, credential, map, memory note,
   report, run, workflow, agent, script, backup, Claude session, etc.
   - Host A open → `#hosts/rt-core-01`; Host B open → `#hosts/sw-acesso-02`.
   - Format: `#<menu>/<stable-id>` — use the stable identifier (name/slug/id), never a list index.
   - Sub-tabs and detail panels too: `#hosts/rt-core-01/interfaces`.
3. **Every filter, search, sort and page = a distinct URL**, as a query inside the hash:
   `#hosts?vendor=mikrotik&status=down&q=core&sort=name&page=2`.
   - Only store non-default values (clean URL when nothing is filtered).
   - Clearing the filter removes the parameter.
   - Combines with an opened item: `#hosts/rt-core-01?tab=interfaces`.
4. **Modals, panels and editors that represent an object** (edit host, view report) also have a URL.
   Confirmations and ephemeral dialogs do not need one.
5. **Opening by URL works** (deep link): on load, the screen reads the hash and restores item, tab and filters;
   a non-existent id shows "not found" with a link back to the menu, never a blank screen.
6. **Normal navigation uses history**: opening an item/tab → `location.hash = ...` (the Back button works).
   A filter change while typing → `history.replaceState` (does not pollute the history).
7. **Real links**: lists use `<a href="#...">`, not an `onClick` that only changes state — this allows opening in
   a new tab and copying the link.
8. **No secrets in the URL**: never put a password, token, secret or sensitive content there (constitution §V).
   No access token in the URL — login is by user and password (sid in the header, never in the URL).
9. **Compatibility**: when renaming a route, redirect the old one (see `topology` → `maps` in `main.js`).
10. **Single helper**: implement/reuse a central helper (e.g.: `useRoute()` in `js/ui.js`) that does the
    parse/serialize of `#menu/id?filters`. Do not scatter manual `location.hash` across the pages.

## Current state (11/11/2026)

All console menus follow the rule. Helpers: `static/js/route.js` (`useMenuRoute`, `useRoute`, `navigate`,
`parseRoute`, `buildRoute`, `matchText`) and `FilterBar` in `components.js`; `ResourceTable` accepts `sortState`/`onSortChange`.

| Menu | Item URL | Filters / parameters |
|------|----------|----------------------|
| Hosts | `#hosts/<id>`, `#hosts/new` | `q vendor role group sort dir` |
| Groups | `#groups/<name>`, `/new` | `q vendor role` |
| Host credentials | `#credentials/<name>`, `/new`, `/<name>/password`, `/<name>/secret` | `q` |
| Maps | `#maps/<map>` (`#maps` → `#maps/all`) | `host=<id>\|new`, `link=<id>` |
| Best practices / Configurations | `#practices\|configs/<vendor>/<file>`, `/new` | `q vendor` |
| Workflows / Agents | `#workflows\|agents/<file>`, `/new` | `q` |
| Reports | `#reports/<file>` | `q` |
| Runs | `#runs/<id>` | `q status` |
| Backups | `#backups/services[/<id>\|/new]`, `#backups/storage[/<host>]` | `q run file diffa diffb` |
| Scripts / Skills | tabs `#scripts` (Skills) and `#scripts?tab=scripts` (Scripts); `#scripts/<skill>` (skill page), `#scripts/<skill>/<file>[?tab=scripts]` (script or `SKILL.md`), `/new` | `tab q location lang sort dir doc` |
| Scheduled tasks | `#schedules/<id>`, `#schedules/new`, `#schedules/runs`, `#schedules/runs/<task>/<run>` | `q kind status` (tasks); `q task rstatus unread` (runs) |
| Dashboard | `#dashboard` (single page) | `range start end model metric` + sorting of the tasks table |
| Settings | `#settings/updates` (updates panel) | — |
| Claude Code | `#claude/<id>`, `#claude/new` | — |
| Users | `#users/<login>`, `#users/new`, `#users/<login>/password` | `q group status sort dir` |
| Access groups | `#access-groups/<name>`, `#access-groups/new` | `q sort dir` |
| Audit | single page (paginated list) | `user action q page sort dir` |
| My account | `#account` (outside the menu; button with the name at the top) | — |
| Projects | `#projects` (list), `#projects/new`, `#projects/<id>` (project sessions), `#projects/<id>/new`, `#projects/<id>/<uuid>` (conversation), `#projects/<id>/files` (folder files) | `arquivados=1` (list of archived), `q` (search in the project sessions); files: `path`, `open`, `q`, `sort`, `hidden` |
| Memory | `#memory` (=MEMORY.md), `#memory/AGENTS.md`, `#memory/notas`, `#memory/<note>.md` | `q` (list of notes) |
| Terminal | single page (no opened item) | — |
| Files | `#files?path=<folder>` (each folder = one history entry; Back = previous folder) | `path q sort hidden open` (`open=<file>` = editor open) |
| Host terminal | `#hostterm/<id>?method=&port=` (own window) | `fpath` = folder of the files panel (stored with replace) |

**Access → Web** (`openWebLaunch`) is an *action* (opens an external tab already logged in via `POST /api/hosts/<id>/web-launch`), not a console screen: it has no hash of its own and never puts a ticket/password in the URL.

Ephemeral filters inside forms/modals (e.g.: choosing hosts when editing a backup service) do not live in the URL.

**Mandatory test:** `scripts/engine/ui/tests/urls.browser.mjs` (isolated environment: `tests/e2e-env.sh up`; see SKILL.md).
When creating a new menu/screen, add a case in `CASES` of that test.

## Checklist before delivering a screen

- [ ] Do opening item A and item B generate different URLs?
- [ ] Does pasting the URL in a new tab restore item, tab and filters?
- [ ] Does each filter/search/sort change the URL?
- [ ] Do the browser's Back/Forward work?
- [ ] No secret in the URL?
- [ ] Does a JS test cover the parse/serialize of the route?
