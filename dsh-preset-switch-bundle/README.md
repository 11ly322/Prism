# dsh-preset-switch (installed bundle)

Mid-session agent-preset switching for DeepSeek Harness. Upstream source:
<https://github.com/the-ninth-moon/dsh-preset-switch> (MIT), commit
`9bac1656eb6edfaa0599e262b236ffa4e79b288e`, version 0.1.0.

Both halves are upstream code with adaptations for this DSH build
(0.2.1-rc.2); each adaptation is marked by its own comment in the source.

## Client (`lib/client.js`)

1. `connection.api` → the `remote` service. Host Remotes no longer live on the
   connection handle.
2. `remote.agentPresets` is read inside `ctx.inject(["remote.agentPresets"], …)`.
   Cordis refuses that property access outside an injection, so the namespace is
   captured when it becomes available and read later by the menu.
3. The roster response is unwrapped from either `{ result: { ok, value } }`
   (the shape upstream expected) or `{ ok, value }`, and a non-array roster can
   no longer break the slot render.

## Host (`lib/index.js`)

The switch is committed by `agentPresets.recompose()` before any bookkeeping.
Upstream then appends a `user/message` carrying the model notice with the
retired V3 wrapper `source: { kind: 'plugin', plugin: 'preset-switch' }`. Session
format v4 refuses that wrapper — *a message requires a producer-owned source
kind* — and `@deepseek-ai/dsh-session-format-v3-to-v4` maps an unknown released
V3 plugin to `plugin:<name>`. The notice therefore uses
`{ kind: 'plugin:preset-switch' }`, and both appends stay best-effort so a
rejected notice can never fail the turn that ran the command.

## Bundle metadata

This directory adds what DSH's Plugin Manager needs to load the package as a
bundle, which upstream does not ship:

- `cordis.patch.yml` + `dsh.bundle.patch` — inserts the `preset-switch` row;
- `dsh.client` — declares the web client half (upstream's
  `@deepseek-ai/dsh-client-runtime` entry is dropped because this build has no
  such package);
- `locale/*.json` and `icon.svg` — display metadata for the Plugins list.

The profile installs this directory as a `link:` dependency, so the folder must
stay at `D:\pictu\dsh-preset-switch-bundle` for the plugin to keep loading.
