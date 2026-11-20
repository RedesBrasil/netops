# Console map editor

React Flow editor integrated into the NetOps Preact SPA. Sources in `maps/`, final assets in
`../static/vendor/map-editor.js` and `map-editor.css`. The operator needs neither Node nor npm.
The build only serves editor maintenance; it does not compile or replace the rest of the console.

## Maintenance

```bash
npm --prefix scripts/engine/ui/maps ci --include=dev
npm --prefix scripts/engine/ui/maps run build
npm --prefix scripts/engine/ui/maps test
```

Pinned dependencies: React Flow `12.12.1`, Preact `10.27.2`, esbuild `0.28.2`.
The build bundles React Flow and its dependencies, but externalizes Preact and its hooks.
An ESM shim adapts React imports to the console's local `preact/compat`, with no React
runtime and no second copy of Preact. `build.mjs` checks this through the metafile.

After rebuilding, update `static/vendor/VERSIONS.txt` with the asset hashes.
Dependency licenses are in `static/vendor/map-editor.LICENSE.txt`.

## Structure and behavior

- `editor.jsx`: `MapEditor` component, with no global mount and no storage of its own.
- `node-state.js`: reconciles nodes while preserving React Flow measurements and selection.
- `parallel-edges.js`: independent lanes and anchors for straight lines.
- `orthogonal-route.js`: unit bends and perpendicular exit at the edges.
- `straight-edges.jsx`: mouse/touch gestures and link controls.
- `editor.css`: styles scoped to `.netops-maps`, with the console themes.
- `test-geometry.mjs`: bend count, orientation and route preservation.
- `../static/js/pages/maps.js`: API controller, revision, save queue and real forms.

Data is stored as YAML on the server and shared across browsers. A host on the map is a
reference to the inventory, never a copy of the record. Connections between hosts use real
links, with optional interfaces. References between maps are visual objects, not fake hosts.

### Integer identity and v2 format

Host IDs are internal, automatic, immutable integers. The form asks only for the editable
name and the other data; host selectors show name/IP. The APIs use integers in `members`,
`host_ids` and `topology.links[].a.host`/`b.host`. The snapshot provides `hosts` as a list of
records with `id`, and positions are a list of `{host_id, x, y, z_index?}`.
The ends of `visual_links` use `{kind: host, host_id: 42}` or
`{kind: object, object_id: forma}`. `maps.yaml` and `topology.yaml` use `version: 2`.

`static/js/host-identity.js` adapts this representation for the editor: ephemeral position
indexes and React Flow node IDs such as `host:42` exist only in the presentation. Every save
and v2 export converts back to lists and typed references with integer IDs. The backend
rejects textual/boolean identity, duplicate host positions and hosts outside the inventory.
A v1 inventory stays visible in read-only mode, with no implicit migration on GET.

`node --test scripts/engine/ui/tests/host-identity.test.mjs` checks this boundary;
`tests/test_maps_identity.py` covers strict validation and legacy reading without writes.
`tests/integer-hosts.browser.mjs` validates desktop/touch: creating hosts from Hosts/Maps with no
ID field, name/IP selectors, integer link, typed visual connection and name editing that preserves
ID, icon, position and link. It uses the same Playwright variables and the same isolated-fixture
requirement as the scenarios below. The main scenario `tests/maps.browser.mjs` also uses v2.

Do not restore the automatic spacing or any other free-movement change removed during the
demo review. The four React Flow handles exist internally, but are invisible.

## Browser test

The integrated test lives in `../tests/maps.browser.mjs`. It uses Playwright and Chromium already
installed by the operator; it does not download tools automatically. Point it only at a
console with fake data, started by the launcher with `NETOPS_UI_DATA_ROOT`.

```bash
NETOPS_E2E_URL=http://127.0.0.1:8771 \
PLAYWRIGHT_MODULE=/caminho/playwright/index.mjs \
CHROMIUM_EXECUTABLE=/caminho/chrome \
node scripts/engine/ui/tests/maps.browser.mjs
```

The test requires an alternate data directory, reported in the console metadata.
It creates test hosts and maps, so it refuses a production instance.

After the integrated host-creation scenario, `tests/maps-endpoints.browser.mjs` validates both
ends on all four sides, with the same environment variables. It uses only the test hosts
created by the previous scenario and also refuses an instance with real data.


## Main view without duplication

When all hosts have the same Site, the selector shows only **Rede geral** (general network) as the
automatic map. Additional maps remain available. Reading computes the merge without writing; the next
save persists the result with revision and backup. Positions and paths of the general map take
precedence, annotations and other adjustments exclusive to the site map are merged in, and old
references start pointing to `all`.

`tests/maps-single-site.browser.mjs` validates desktop and touch with a test directory containing
the examples `hosts.example.yaml`/`topology.example.yaml` and a `maps.yaml` fixture: general map with
saved positions, a `matriz` map with the note “Anotação preservada da matriz” and an additional map
with a reference to the old `matriz`. Use the same Playwright variables as the previous tests.


## Stable dragging

The autosave confirmation and polling do not recreate nodes that are already measured. `reconcileNodes`
keeps `measured`, selection and transient state, applying only the layout/inventory changes.
Dragging and resizing use the current state by reference; the YAML is saved only when the gesture
ends. Read responses started before an edit are discarded, and an earlier save confirmation does
not change the position of a host that is still moving.

`tests/maps-drag.browser.mjs` simulates delayed GET/PUT, consecutive drags and refreshes with no
changes on desktop and touch, monitoring node visibility through MutationObserver and per frame.
It requires an isolated console with the example hosts and accepts the Playwright variables of the
other tests. `npm test` in the editor also runs the node-state preservation tests.


## Local host icons

The editor renders the host's `icon` field with thumbnails from `static/icons/network/thumbnails/`.
The catalog is embedded in the build only to resolve allowed local IDs; the setting lives in
the inventory, not in the layout. An invalid/unavailable image falls back to the previous symbol,
and its reserved size keeps the host from moving while it loads.
When updating the library, rebuild the editor after `vendor_icons.py`.


## Compact controls and context menus

The map fills all the available area below a single row: current map, **+** for a new
map, and export. Editing actions moved to the right-click menu on the background, on nodes,
on the line/label of links and on corners. Normal selection keeps the A/B geometry controls
and draggable corners, without opening a second action bar.

On touch, **⋯** uses the selected item, or the background when nothing is selected. **Shift+F10** opens
the menu of the focused/selected item; arrows navigate and Escape closes. Menus are confined to the
viewport, with scrolling in landscape. The menu does not include speed, host list, export,
legend/help or new map. New map and export stay only at the top; speed remains
in the link form.

`tests/maps-context.browser.mjs` covers the removal of the old items, the single row, creation and
editing through the menu, bends, export, shortcuts and conflict recovery with mouse and touch.
`tests/maps-actions.mjs` is the gesture helper for the browser scenarios, not UI code.
The inventory/layout files and the autosave flow remain the same.


## Connectable shapes and groups

`Shape` uses the same invisible `NodeHandles` as hosts. The single connection flow accepts
shapes as source/target and reuses `visual_links`; it does not create hosts without an IP. The icon
catalog is validated in `MapObject`, while the shared `IconPicker` is received from the SPA
as a prop, without duplicating components/API/Preact in the bundle.

Multiple selection uses React Flow's `node.selected`, its Ctrl/Meta modifiers and rectangle
selection with the left button on the background, without modifiers (Shift also works).
The rectangle selects items that are fully contained; the middle button or Space pans
the map, and the touch drag gesture keeps navigating. The group menu and the touch alternative call `alignNodes` in
`node-state.js`, a pure function that returns positions by ID, sorted along the axis and separated by
24 units between edges. The editor applies host and object positions in a single save.
Reconciliation keeps measurements/selection and no route is reset by alignment.

`tests/shapes-align.browser.mjs` covers connections in both directions, icons, persistence,
selection of four hosts, mixed group, equal spacing and unselected devices left
intact. Run it on an exclusive isolated fixture, with no concurrent scenarios changing
the same maps file.

## Optional text, colors and layers

Real links show only `desc`, editable in the link form. Visual connections use
`label` and start with empty text; neither speed nor generic names generate labels. Shapes
can also have empty text. The line remains selectable to adjust/edit the connection.

The shape form offers native fill and outline pickers, editable/copyable HEX fields
and a preview. Optional `color` and `stroke` use `#RRGGBB` in `maps.yaml`.
The text of the shape and of the preview uses black or white according to the fill luminance,
keeping contrast regardless of the console theme.
Old objects without these fields keep the theme colors until they are edited.

Hosts, objects (shapes, notes, references) and links (physical links and visual connections)
share ONE layer stack, saved in `positions[].z_index` (matched by the integer
`positions[].host_id`), `objects[].z_index`, `edges.<id>.z_index` and `visual_links[].z_index`.
React Flow runs with `zIndexMode="manual"` and without raising on selection, so the displayed layer is
exactly the saved one. Node and link menu: Bring to top / Bring forward / Send
backward / Send to bottom. Forward/backward jump past the next item that geometrically
**overlaps** the target (node rectangle; center-to-center segment for links,
or bounding box if there are bends); with no overlap, it moves one layer. Without `z_index`,
shapes sit at the bottom and links just below the lowest device. Link labels are
always on top (React Flow's own layer). Selection does not change the layer.
Moving/aligning a host preserves its layer. Duplicate creates another shape with its own ID, same
colors/icon/size/text, offset by 32 units and one layer above the original.

Ctrl+Z undoes and Ctrl+Shift+Z / Ctrl+Y redo (↶ ↷ buttons in the bar) up to 10 layout
changes per map: move/resize (1 step per gesture), layers, create/edit/duplicate/
remove shapes, notes and visual connections, remove a host from an additional map, align, rename.
The restored state is reconciled with the current inventory/topology (`reconcileLayout`).
Canonical deletions (inventory host, topology link) do NOT go into the history.
The history resets when switching maps and is ignored in text fields and in the terminal.

Delete removes the selected objects and their visual connections. In additional maps, selected
hosts are only removed from the map. In automatic maps, a selection containing hosts opens an
explicit confirmation to delete them from the inventory and their links/references in all maps.
The operation uses one revision per deletion and stops at the first failure, reporting how many
hosts were already removed; it is not a single transaction for the whole group. The map is read-only
during the sequence. Delete inside text fields keeps normal editing.

`node-state.test.mjs` covers the mixed stack, limits, duplication and group cleanup without mutating
the previous snapshot. `tests/maps-editing.browser.mjs` checks these features in the browser
with isolated fake data.

React Flow omits `onPaneClick` on touch when `selectionOnDrag` is active. The canvas
recognizes a short tap on the background by `pointerId` and a maximum movement of 6px to clear
the selection; drags remain panning and mouse selection stays available on
hybrid devices too. Multiple selection, connection and duplication return focus to the canvas,
allowing Escape/Delete right after the menu closes.

Choosing a connection by click, right-click or Shift+F10 clears the previous node selection
before enabling Delete. This way the deletion acts only on the chosen connection
(physical link with confirmation), preserving the previously selected shapes/hosts.
A menu opened on a node that is part of a multiple selection keeps the group selected.
