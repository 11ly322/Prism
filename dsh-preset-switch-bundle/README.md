# dsh-preset-switch (installed bundle)

Mid-session agent-preset switching for DeepSeek Harness. Upstream source:
<https://github.com/the-ninth-moon/dsh-preset-switch> (MIT), commit
`9bac165`, version 0.1.0.

Both halves are upstream code with adaptations for this DSH build
(0.2.1-rc.2); each adaptation is marked by its own comment in the source.

## Client (`lib/client.js`)

1. `connection.api` -> the `remote` service, read inside
   `ctx.inject(["remote.agentPresets"], ...)`: the property is gated, so it is
   captured when the namespace becomes available.
2. The roster response is unwrapped from either `{ result: { ok, value } }` or
   `{ ok, value }`, and a non-array roster can no longer break the slot render.
3. Shipped presets publish no `name`; their copy resolves through the same
   `BUILT_IN_PRESET_KEYS` fold the registry uses (Standard / PTC / Minimal /
   Creator mode), and an unnamed custom preset falls back to its id.

## Host (`lib/index.js`)

The switch is committed by `agentPresets.recompose()` before any bookkeeping.
The model notice is appended with the producer-owned source kind
`plugin:preset-switch` (session format v4 refuses the retired `plugin`
wrapper). Both appends stay best-effort, and the handler keeps a final
`run.catch`, so a rejected notice can never fail the turn that ran the command.

## Bundle metadata

- `cordis.patch.yml` + `dsh.bundle.patch` — inserts the `preset-switch` row;
- `dsh.client` — declares the web client half;
- `locale/*.json` and `icon.svg` — display metadata for the Plugins list.

The profile installs this directory as a `link:` dependency, so the folder must
stay at `D:\pictu\dsh-preset-switch-bundle` for the plugin to keep loading.
