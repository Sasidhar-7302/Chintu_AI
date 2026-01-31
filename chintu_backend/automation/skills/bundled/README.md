# Bundled Skills (Ship with Backend)

These are the built-in skills that ship with Chintu's backend. They provide the default behaviors for common actions. Do **not** edit these if you want an easy upgrade path; instead add/override skills in the workspace layer:
- Workspace skills: `skills/`
- User profile skills: `~/.chintu/skills/`

Load order (highest priority first):
1. `skills/` (workspace)
2. `~/.chintu/skills/` (user)
3. `chintu/skills/bundled/` (these)

If you must patch a bundled skill, copy it into `skills/` and edit there to keep the original intact.
