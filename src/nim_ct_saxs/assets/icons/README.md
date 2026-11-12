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
| View controls help | Quasar Material Icons font | `help_outline` |

SVG calls are in `ui.py` and the project dialog builder in `project_workflow.py`;
font-icon calls are `quasar.QIcon(name=...)` in `ui.py`.
Dockview supplies its own tab-close and group-control SVG icons.

The local SVGs were copied from Exhale’s `exhale/resources/icons` collection
and adapted to use CSS colours. These are Tabler icons by Paweł Kuna; the MIT
licence is included in `LICENSE-icons.txt`.
