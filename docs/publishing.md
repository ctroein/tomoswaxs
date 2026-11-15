# GitHub publication

The public repository is [ctroein/tomoswaxs](https://github.com/ctroein/tomoswaxs).
This source checkout has its own existing Git history. Run the commands below
from the checkout containing `pyproject.toml` and `src/tomoswaxs/`.

Review `git status` and the changes before creating the next local commit.
Include new source files and tests required by the application; leave generated
files and local IDE settings out of Git. The package rename also requires staging
the removal of the old `src/nim_ct_saxs/` paths along with the new
`src/tomoswaxs/` paths. The root MIT `LICENSE` and About text
list Carl Troein, Emanuel Larsson, Mira Viljanen, Daniel White and Stuart Ansell.

Once local changes have been reviewed and committed, connect the remote:

```sh
git remote add origin https://github.com/ctroein/tomoswaxs.git
git fetch origin
git log --oneline --graph --all
```

GitHub was initialized separately with a licence commit. If that history remains
independent, merge it into the local branch rather than replacing either history:

```sh
git merge --allow-unrelated-histories origin/main
```

If `LICENSE` conflicts, retain the local MIT text with all five copyright holders,
then stage the resolved file and complete the merge with `git commit`.
Review any other conflicts before completing the merge. `git merge --abort`
cancels an unfinished merge.

Publish the current local branch as GitHub's `main`:

```sh
git push -u origin HEAD:main
```

HTTPS pushes require GitHub authentication with repository write access. No
remote connection, merge, commit or push is performed by these instructions.
