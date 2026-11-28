# Icons

Application icons use Quasar’s Material Icons font through `quasar.QIcon(name=...)`.
The `.app-icon` CSS class supplies the theme’s teal accent where appropriate.

| UI use | Source | Reference in code |
| --- | --- | --- |
| Browse directories/projects | Quasar Material Icons font | `folder_open` |
| Rotation settings | Quasar Material Icons font | `tune` |
| Play rotation | Quasar Material Icons font | `play_arrow` |
| Pause rotation | Quasar Material Icons font | `pause` |
| Open/return a detached panel | Quasar Material Icons font | `open_in_new` (rotated for return) |
| Close a panel tab | NIM tab renderer | `×` |
| View controls help | Quasar Material Icons font | `help_outline` |
| Application settings | Quasar Material Icons font | `settings` |
| Lock/unlock approximate SAXS X | Quasar Material Icons font | `lock` / `lock_open` |
| Copy crop coordinates | Quasar Material Icons font | `content_copy` |

Icon calls are in `ui.py`, `workspace.py` and `saxs_ui.py`.
The tab renderer is in `workspace.py`. Dockview supplies group controls.
