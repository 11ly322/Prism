/**
 * dsh-preset-switch — client half.
 *
 * Renders a small mode-switch button in the `conversation.input.left` seat of
 * the composer tool row — immediately beside the access-mode (permission)
 * control. The menu lists the agent-preset roster from the existing
 * `agentPresets.list` Remote; selecting one runs the `/preset <id>` command
 * through the session command channel, exactly like the shipped /permission
 * picker.
 *
 * This file is a browser module in the dsh client module format: the loader
 * wraps it, and `require` resolves against the scanned dsh.client module
 * table. Only `react` is required; everything else comes from ctx services.
 */
window.__ModuleLoader__.load({
  id: "dsh-preset-switch",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
    let react = require("react");

    const NS = "preset.switch";
    const inject = ["slots", "locale", "sessions", "remote"];
    // Shipped presets publish no `name`: their copy lives in these dictionary
    // keys. This mirrors @deepseek-ai/dsh-agent-preset-registry/display, whose
    // presetDisplayText() every shipped surface uses for the same roster.
    const BUILT_IN_PRESET_KEYS = {
      standard: ["presetStandardName", "presetStandardDescription"],
      ptc: ["presetPtcName", "presetPtcDescription"],
      minimal: ["presetMinimalName", "presetMinimalDescription"],
      cordis: ["presetCordisName", "presetCordisDescription"]
    };

    function apply(ctx) {
      const locale = ctx.get("locale");
      if (locale !== undefined) {
        ctx.effect(() => locale.register(NS, "zh", {
          aria: "切换 Agent 模式",
          current: "当前模式：{name}",
          switching: "切换中…",
          failed: "切换失败：{message}",
          empty: "暂无可用模式",
          user: "自定义",
          presetStandardName: "标准模式",
          presetStandardDescription: "处理代码、文件和资料，适合大多数任务。Agent 会按需使用检索、编辑和终端等工具。",
          presetPtcName: "PTC 模式",
          presetPtcDescription: "包含标准模式的所有能力，更适合批量调用工具，并对结果进行筛选、整理、去重、统计或汇总的任务。",
          presetMinimalName: "极简模式",
          presetMinimalDescription: "Agent 使用终端和图片读取工具，并支持上下文压缩，适合测试和对比其基础表现。",
          presetCordisName: "创造模式",
          presetCordisDescription: "用对话定制 DSH：让 Agent 编写插件，添加新功能或界面；也能组合工具和提示词，创建自己的模式。"
        }), "preset-switch: zh dict");
        ctx.effect(() => locale.register(NS, "en", {
          aria: "Switch agent preset",
          current: "Current mode: {name}",
          switching: "Switching…",
          failed: "Switch failed: {message}",
          empty: "No presets available",
          user: "Custom",
          presetStandardName: "Standard mode",
          presetStandardDescription: "Work with code, files, and information. Suitable for most tasks, with search, editing, terminal commands, and other tools available as needed.",
          presetPtcName: "PTC mode",
          presetPtcDescription: "Includes all Standard mode capabilities. Better suited to tasks that call tools in batches and then filter, organize, deduplicate, count, or summarize the results.",
          presetMinimalName: "Minimal mode",
          presetMinimalDescription: "The agent uses a terminal and image reading, with context compaction. Useful for testing and comparing its basic performance.",
          presetCordisName: "Creator mode",
          presetCordisDescription: "Customize DSH through conversation. Let the agent write plugins that add features or UI, or combine tools and prompts to create your own mode."
        }), "preset-switch: en dict");
      }
      const t = locale === undefined ? (key, params) => {
        const fallback = {
          aria: "切换 Agent 模式",
          current: "当前模式：{name}",
          switching: "切换中…",
          failed: "切换失败：{message}",
          empty: "暂无可用模式",
          user: "自定义",
          presetStandardName: "标准模式",
          presetStandardDescription: "处理代码、文件和资料，适合大多数任务。Agent 会按需使用检索、编辑和终端等工具。",
          presetPtcName: "PTC 模式",
          presetPtcDescription: "包含标准模式的所有能力，更适合批量调用工具，并对结果进行筛选、整理、去重、统计或汇总的任务。",
          presetMinimalName: "极简模式",
          presetMinimalDescription: "Agent 使用终端和图片读取工具，并支持上下文压缩，适合测试和对比其基础表现。",
          presetCordisName: "创造模式",
          presetCordisDescription: "用对话定制 DSH：让 Agent 编写插件，添加新功能或界面；也能组合工具和提示词，创建自己的模式。"
        };
        let text = fallback[key] ?? key;
        if (params !== undefined) for (const k of Object.keys(params)) text = text.replaceAll(`{${k}}`, String(params[k]));
        return text;
      } : locale.bind(NS);

      // Every Remote namespace is gated behind an injection: the `remote`
      // service is reachable, but reading `remote.agentPresets` throws until
      // that exact key is injected. Older builds carried the same surface on
      // `connection.api`.
      let presetRemote;
      ctx.inject(["remote.agentPresets"], (scope) => {
        presetRemote = scope.remote.agentPresets;
        return () => { presetRemote = undefined; };
      });
      const sessions = ctx.get("sessions");

      ctx.slots.inject("conversation.input.left", () => ctx.slots.register(
        { name: "conversation.input.left", id: "preset-switch", order: -50 },
        (props) => {
          const sessionId = props.sessionId;
          const useSessions = props.useSessions;
          const currentPreset = useSessions((state) => state.byId[sessionId]?.agentPreset);
          const [open, setOpen] = react.useState(false);
          const [roster, setRoster] = react.useState(null);
          const [error, setError] = react.useState(null);
          const [busy, setBusy] = react.useState(false);
          const [current, setCurrent] = react.useState(currentPreset);
          const rootRef = react.useRef(null);
          react.useEffect(() => setCurrent(currentPreset), [currentPreset]);
          react.useEffect(() => {
            if (!open) return;
            const onPointerDown = (ev) => {
              if (rootRef.current !== null && ev.target instanceof Node && rootRef.current.contains(ev.target)) return;
              setOpen(false);
            };
            document.addEventListener("pointerdown", onPointerDown, true);
            return () => document.removeEventListener("pointerdown", onPointerDown, true);
          }, [open]);
          const load = async () => {
            const remote = presetRemote ?? ctx.get("connection")?.api?.agentPresets;
            if (remote === undefined) {
              setError("agent preset remote unavailable");
              return;
            }
            try {
              const response = await remote.list();
              const result = response?.result ?? response;
              if (result?.ok === false) {
                setError(String(result.error?.message ?? "could not load agent presets"));
                return;
              }
              const value = result?.ok === true ? result.value : result;
              const presets = Array.isArray(value?.presets) ? value.presets : (Array.isArray(value) ? value : null);
              if (presets === null) {
                setError("could not load agent presets");
                return;
              }
              setRoster(presets);
              setError(null);
            } catch (e) {
              setError(String(e && e.message ? e.message : e));
            }
          };
          const switchTo = async (id) => {
            if (id === current) {
              setOpen(false);
              return;
            }
            if (sessions === undefined) {
              setError("sessions service unavailable");
              return;
            }
            const live = sessions.binding(sessionId)?.session;
            if (live === undefined) {
              setError("session is not materialized yet");
              return;
            }
            setBusy(true);
            setError(null);
            try {
              const result = await live.command(`/preset ${id}`);
              if (!result.ok) {
                setError(String(result.error && result.error.message ? result.error.message : "command failed"));
              } else {
                setCurrent(id);
                setOpen(false);
              }
            } catch (e) {
              setError(String(e && e.message ? e.message : e));
            } finally {
              setBusy(false);
            }
          };
          const toggle = () => {
            if (!open) load();
            setOpen(!open);
          };
          const items = Array.isArray(roster) ? roster : [];
          const displayOf = (p) => {
            const keys = p.name === undefined ? BUILT_IN_PRESET_KEYS[p.id] : undefined;
            if (keys !== undefined) return { name: t(keys[0]), description: t(keys[1]) };
            return { name: p.name ?? p.id, description: p.description };
          };
          const currentName = (() => {
            const entry = items.find((p) => p.id === current);
            if (entry === undefined) return current ?? "";
            const copy = displayOf(entry);
            return entry.trust === "user" ? `${copy.name} · ${t("user")}` : copy.name;
          })();
          const label = busy ? t("switching") : (currentName !== "" ? currentName : "");
          return react.createElement("span", { ref: rootRef, style: { position: "relative", display: "inline-flex" } },
            react.createElement("button", {
              type: "button",
              disabled: busy,
              "aria-haspopup": "menu",
              "aria-expanded": open,
              "aria-label": t("aria"),
              title: t("current", { name: label === "" ? current : label }),
              onClick: toggle,
              style: {
                height: 28,
                maxWidth: 180,
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                padding: "0 8px",
                border: "none",
                borderRadius: 999,
                background: "transparent",
                color: "var(--dsw-alias-label-secondary)",
                cursor: "pointer",
                fontSize: 13,
                lineHeight: "20px",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                font: "inherit"
              }
            },
              react.createElement("span", { "aria-hidden": true, style: { fontSize: 14, flex: "none" } }, "⇄"),
              react.createElement("span", { style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, label)
            ),
            open && react.createElement("div", {
              role: "menu",
              style: {
                position: "absolute",
                bottom: "calc(100% + 8px)",
                left: 0,
                zIndex: 100,
                minWidth: 220,
                maxWidth: 300,
                maxHeight: 320,
                overflowY: "auto",
                background: "var(--dsw-specific-menu)",
                border: "1px solid var(--dsw-alias-border-l2)",
                borderRadius: 12,
                boxShadow: "var(--dsw-shadow-lv3)",
                padding: 4,
                display: "flex",
                flexDirection: "column",
                gap: 2
              },
              onMouseDown: (e) => e.preventDefault()
            },
              error !== null && react.createElement("div", {
                style: { color: "var(--dsw-alias-state-error-primary)", fontSize: 12, padding: "4px 8px", maxWidth: 280 }
              }, t("failed", { message: error })),
              items.length === 0 && error === null && react.createElement("div", {
                style: { color: "var(--dsw-alias-label-caption)", fontSize: 12, padding: "4px 8px" }
              }, t("empty")),
              items.map((p) => {
                const copy = displayOf(p);
                return react.createElement("button", {
                  key: p.id,
                  type: "button",
                  role: "menuitem",
                  disabled: busy,
                  onClick: () => switchTo(p.id),
                  title: copy.description ?? p.id,
                  style: {
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "flex-start",
                    gap: 2,
                    padding: "6px 10px",
                    border: "none",
                    borderRadius: 8,
                    background: p.id === current ? "var(--dsw-alias-interactive-bg-hover)" : "transparent",
                    color: "var(--dsw-alias-label-primary)",
                    cursor: "pointer",
                    textAlign: "left",
                    font: "inherit",
                    fontSize: 13,
                    lineHeight: "18px",
                    width: "100%"
                  }
                },
                  react.createElement("span", { style: { fontWeight: 500 } },
                    copy.name + (p.trust === "user" ? ` · ${t("user")}` : "")),
                  copy.description !== undefined && react.createElement("span", {
                    style: { color: "var(--dsw-alias-label-caption)", fontSize: 12, maxWidth: 260, whiteSpace: "normal" }
                  }, copy.description)
                );
              })
            )
          );
        }
      ));
    }

    exports.apply = apply;
    exports.inject = inject;
    return module.exports;
  }
});
