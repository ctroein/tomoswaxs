# Icons

Local SVGs are embedded inline by `ApplicationUI.svg_icon()` and use
`currentColor` for their strokes. The `.app-icon` CSS class supplies the theme’s
teal accent. The folder icon retains its orange fill.

| UI use | Source | Reference in code |
| --- | --- | --- |
| Browse directories/projects | Local Tabler SVG | `folder-open.svg` |
| Rotation settings | Local Tabler SVG | `adjustments.svg` |
| Play rotation | Quasar Material Icons font | `play_arrow` |
| Pause rotation | Quasar Material Icons font | `pause` |
| Open/return a detached panel | Local NIM SVG | `open-window.svg` |
| Close a panel tab | NIM tab renderer | `×` |
| View controls help | Quasar Material Icons font | `help_outline` |
| Application settings | Quasar Material Icons font | `settings` |
| Lock/unlock approximate SAXS X | Quasar Material Icons font | `lock` / `lock_open` |
| Copy crop coordinates | Quasar Material Icons font | `content_copy` |

SVG calls are in `ui.py` and the project dialog builder in `project_workflow.py`;
font-icon calls are `quasar.QIcon(name=...)` in `ui.py`.
The tab renderer is in `workspace.py`. Dockview supplies group controls.
`open-window.svg` is a NIM project icon, covered by the project MIT licence.

The local SVGs were copied from Exhale’s `exhale/resources/icons` collection
and adapted to use CSS colours. These are Tabler icons by Paweł Kuna; the MIT
licence is included in `LICENSE-icons.txt`.
