# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An MCP server that lets an LLM drive the Unreal Editor. Two halves:

- **`mcp-server/`** — Python FastMCP server (the MCP side, talks to the LLM over stdio).
- **`Plugins/UnrealMCPython/`** — a UE plugin: a C++ TCP server (port `12029`) plus
  Python "action" modules that actually call the Unreal API.

Request path: `LLM → FastMCP dispatcher → TCP :12029 → C++ server → ue_* Python function → back`.

## Architecture (the non-obvious parts)

**Namespace dispatcher, not one-tool-per-action.** The MCP surface is **21 domain tools**
(one per key of `CATALOG`: `actor`, `anim_blueprint`, `animation`, `asset`, `behavior_tree`,
`blueprint`, `control_rig`, `data_table`, `editor`, `game`, `gas`, `layer`, `level`,
`level_sequence`, `material`, `retarget`, `static_mesh`, `texture`, `umg`, `util`,
`vision`), each taking `(action, params)`. This keeps the tool-list context cost fixed
no matter how many actions exist. `action="list_actions"` returns a domain's catalog.
See `mcp-server/src/unreal_mcp/dispatcher.py`.

**The catalog is generated, never hand-written.** `dispatchers/_catalog.py` is produced by
`generate_catalog.py`, which AST-extracts param names, defaults, and the docstring first line
from every `ue_*` function in `Plugins/.../UnrealMCPython/*_actions.py`. The dispatcher passes
`params` straight through as `ue_<action>(**params)`, so catalog param names **must** equal the
real signatures — generation guarantees this. Never edit `_catalog.py` by hand.

**Responses are double-wrapped.** The C++ server runs `print(execute_action(...))` and puts the
captured stdout (the action's JSON string) into a `result` field, with an outer `success` that
means "Python ran", not "action succeeded". `core._unwrap_result()` unwraps it so callers get the
real action dict. `execute_python` / `livecoding_compile` use separate TCP message types and are
intentionally not unwrapped.

## Commands

```bash
# All run from mcp-server/
cd mcp-server

# Regenerate the catalog after adding/changing a ue_* function
uv run python generate_catalog.py

# Gate 1 — catalog vs signatures drift guard
uv run python validate_tools.py

# Gate 2 — offline tests (routing, unwrap, coverage). E2E auto-skips with no editor.
uv run --extra dev pytest

# Single test / by name
uv run --extra dev pytest tests/test_dispatcher.py -k routing
```

In-editor tests (need the editor open) run from the Unreal Python console or via
`util execute_python`:

```python
import runpy; runpy.run_module("UnrealMCPython.tests.run_all", run_name="__main__")
```

## Four test gates (each catches a different failure)

| Gate | Command | Verifies | Editor |
|------|---------|----------|--------|
| 1 Drift | `validate_tools.py` | catalog param names == `ue_*` signatures | no |
| 2 Routing | `pytest tests/test_dispatcher.py` `test_core.py` | dispatcher routing + result unwrapping | no |
| 3 In-editor | `tests/run_all.py` in UE | `ue_*` actually work against Unreal | yes |
| 4 E2E | `pytest tests/test_e2e.py` | full chain incl. TCP + unwrap (skips if `:12029` closed) | yes |

`test_coverage.py` enforces that **every** catalog action has an in-editor test
(or is listed in `KNOWN_UNTESTED`, which should stay empty).

**E2E editor-crash guard**: if the editor dies mid-suite, the remaining E2E tests FAIL
(autouse fixture + connection-error assertions + a final liveness canary). A green E2E
run therefore guarantees the editor survived the whole sweep — never chain
`pytest && git commit && gh pr create` assuming connection-error results count as
passes. Release chains stop at the first red gate.

### Running the gates without taking the machine down

**Silence `LogRendererCore` when launching an editor for the suite.** Validate-on-save
re-enters Slate from a `SlowTask` progress refresh and can spin `FlushRenderingCommands`
recursively, logging `FlushRenderingCommands called recursively! 2 calls on the stack.`
in a tight loop. Measured once at **1,073,165 lines / 131 MB in a single session**, enough
to hard-freeze the machine. The suite saves constantly (278 packages in one run), so it
hits this readily:

```bash
UnrealEditor UnrealMCPSample.uproject -LogCmds="LogRendererCore off" \
  '-ini:EditorPerProjectUserSettings:[/Script/UnrealEd.EditorLoadingSavingSettings]:bAutoSaveEnable=False'
```

**Disable autosave for the same launch.** E2E spawns actors into the open (untitled) level
and never cleans them up, so autosave eventually fires on a map full of test actors while
the suite is still running. The game thread parks in `SavePackage`, every request in that
window hits the 30s client timeout, and a whole domain fails at once — one run went
`26 failed, 530 passed in 841.22s`, all 26 in `actor`, purely from timeouts
(26 × 30s ≈ the entire runtime). With autosave off the same suite is `556 passed in 4.42s`.
The signature in the log is `Cmd: OBJ SAVEPACKAGE PACKAGE="/Temp/Untitled_1" ... AUTOSAVING=true`.
The setting is **not reachable from Python** — `unreal.EditorLoadingSavingSettings` is not
exposed, `set_editor_property("auto_save_enable")` on the CDO fails (no script visibility),
and `MCPythonHelper.SetClassPropertyRaw` only writes `UClass`-typed properties. The
command-line `-ini:` override above is the way; it touches no file on disk. Verify it took
by the absence of `AUTOSAVING=true` in the log **paired with** a positive control that saves
did happen (`grep -c SavePackage`).

Disabling the trigger instead (`bValidateOnSave=False` under
`[/Script/DataValidation.DataValidationSettings]` in `Config/DefaultEditor.ini`) also works
and was verified, but it changes save behaviour for everyone who opens the project, so it
is deliberately **not** committed. Note the property on `UEditorValidatorSubsystem` of the
same name is `DeprecatedProperty` and setting it does nothing — only the
`UDataValidationSettings` one is read.

**Let the editor settle between gate 3 and gate 4.** Running E2E straight after the ~90s
in-editor suite invites DDC maintenance to land on top of it — one run stalled the game
thread ~190s (`LogDerivedDataCache: Maintenance finished in +00:01:04`, then a silent gap;
`LogAutomationController` logged `Ignoring very large delta of 251.27 seconds`). The E2E
client times out at 30s, so everything in that window fails with `No response from Unreal`
and reads as a block of unrelated failures. A failure block that is *consecutive* in one
domain plus one heavy test is a stall signature, not N independent bugs — check whether
the editor is still alive before diagnosing further.

**After a `kill -9`, the relaunched editor logs a TCP server it does not have.**
`LogMCPython: TCP server started at 127.0.0.1:12029.` is printed even when the bind failed,
so the log reads clean while every client gets `ConnectionRefusedError` and `ss -ltn` shows
no listener at all. Killing the editor hard leaves the socket held long enough to poison the
next launch. Close the editor normally when it still responds; after a forced kill, wait for
the port to clear before relaunching. Also note an empty `/dev/tcp` probe is not a readiness
check — poll with a real `{"type": "python"}` request instead.

**A leftover test asset fails the whole test class, silently.** `MCPTestCase.delete_asset`
wraps the delete in `except Exception: pass`, so when a previous run died mid-suite and left
e.g. `MCP_TestAnimBP` behind, `setUp` fails to remove it without saying so and every test in
the class then dies on `Asset already exists: /Game/Tests/MCP/MCP_TestAnimBP`. `Content/Tests/`
is gitignored — delete the stale `.uasset` files on disk with the editor **closed** and rerun.
Deleting one through `EditorAssetLibrary.delete_asset` while the editor is up opens a modal
that blocks the game thread with no log line, which then needs the forced kill above.

**A socket timeout is not a red gate 3.** `core.send_python_exec` hardcodes `TIMEOUT = 30`,
shorter than the ~90s suite, so driving `run_all.py` through it *always* reports a timeout
even on a green run. Use a client with a longer timeout, or read the verdict from the log
(`Ran N tests` / `OK (skipped=…)`).

**Grep the right log.** If an editor is already running, UE writes to `UnrealMCPSample_2.log`
instead of `UnrealMCPSample.log`. Greps against the stale file return zeros that look like
clean results. Check `ls -t Saved/Logs/*.log` first, and pair any "absence" check with a
positive control (e.g. assert saves happened before concluding validation did not run).

## Adding an action to an existing domain

1. Prototype fast with `util execute_python` (arbitrary Unreal Python, seconds-scale).
2. Add a `ue_<name>(...)` function to `Plugins/.../UnrealMCPython/<domain>_actions.py`.
   It must `return json.dumps({...})` and validate its own required params.
3. Add an in-editor test in `Plugins/.../UnrealMCPython/tests/test_<domain>.py`
   (the coverage gate fails without one).
4. `uv run python generate_catalog.py` — the action now appears in the dispatcher.
5. Run gates: `uv run python validate_tools.py` and `uv run --extra dev pytest`,
   then the in-editor suite (and E2E if the editor is up).
6. Commit.

```python
# Plugins/.../UnrealMCPython/<domain>_actions.py
def ue_my_action(asset_path: str = None, value: float = 1.0) -> str:
    """One-line summary becomes the catalog doc."""
    if asset_path is None:
        return json.dumps({"success": False, "message": "Required parameter 'asset_path' is missing."})
    try:
        # ... call the Unreal API ...
        return json.dumps({"success": True, "result_field": ...})
    except Exception as e:
        return json.dumps({"success": False, "message": str(e), "traceback": traceback.format_exc()})
```

```python
# Plugins/.../UnrealMCPython/tests/test_<domain>.py
def test_my_action(self):
    r = self.call("<domain>_actions", "ue_my_action", asset_path=self._asset, value=2.0)
    self.assertSuccess(r)
```

## Adding a new domain

1. Create `Plugins/.../UnrealMCPython/<domain>_actions.py` with `ue_*` functions.
2. Create `Plugins/.../UnrealMCPython/tests/test_<domain>.py` and add the module to
   `tests/run_all.py`.
3. Add `"<domain>"` to `DOMAINS` in `generate_catalog.py` (the module is derived as
   `UnrealMCPython.<domain>_actions`). The dispatcher auto-registers every catalog
   domain except the special-routed ones (`util`, `vision`) — no `dispatcher.py` edit needed.
4. `uv run python generate_catalog.py`, then run the gates.

Special-routed domains have hand-written handlers in `dispatcher.py` (`_SPECIAL_DOMAINS`):
- **util** — `execute_python` / `livecoding_compile` use dedicated TCP message types.
- **vision** — `capture_viewport` returns an MCP `Image` (the action sends back base64
  PNG in `image_data`; the handler decodes it). Viewport capture uses a transient
  SceneCapture2D → RGBA8 render target → PNG, which works regardless of editor focus
  (unlike `take_high_res_screenshot`, which only fires when the viewport renders).

Follow these patterns only if an action isn't a plain `ue_*` JSON call. Special-routed
actions that aren't plain dicts (e.g. vision capture) must be excluded from the E2E
empty-param sweep (`_EXCLUDE` in test_e2e.py) and the offline routing parametrization.

## Adding C++ helpers (UFUNCTIONs in MCPythonHelper)

Some APIs aren't exposed to Python (e.g. reference-skeleton bones, read-only
`SkeletalMeshSocket.socket_name`, Blueprint/AnimBP graph internals). Add a
`UFUNCTION(BlueprintCallable, Category="Editor|MCPython")` to
`Source/UnrealMCPython/Public/MCPythonHelper.h` + impl in the `.cpp` (return a JSON
string via `SerializeJsonObj`), then call it from a Python `ue_*` wrapper.

**Build cycle — this matters:**
- Editing an existing function *body* → `util livecoding_compile` hot-patches the
  running editor. Fast. **Windows only** (see below).
- **Adding a new UFUNCTION** (new reflection) → Live Coding compiles but does NOT
  register it. You must do a full UBT build with the editor **closed**
  (this is a plugin-only project — there is no project-level target):
  1. Close the editor completely (verify no `UnrealEditor` process remains).
  2. Build the editor target for your platform:
     - Windows — `"<UE>/Engine/Build/BatchFiles/Build.bat" UnrealEditor Win64 Development -project="<repo>/UnrealMCPSample.uproject" -waitmutex`
     - Linux — `"<UE>/Engine/Build/BatchFiles/Linux/Build.sh" UnrealEditor Linux Development -project="<repo>/UnrealMCPSample.uproject" -waitmutex`
  3. Reopen the editor; the new UFUNCTION is now callable from Python.

**Platform note — Live Coding is Windows-only.** The module does not exist on
Linux, so everything Live Coding is compiled out behind `WITH_LIVE_CODING`
(`.Build.cs` adds the dependency only under `Target.bWithLiveCoding`; the TCP
handler, its log capture and `HandleLiveCodingCompile` are `#if`-guarded). On a
Linux editor `util livecoding_compile` therefore fails with an actionable
message instead of silently reporting a clean compile, and **every** C++ change —
not just a new UFUNCTION — needs the full editor-closed rebuild above.

## Conventions

- `ue_*` functions take keyword args matching catalog param names and return a JSON string.
- Required params are validated inside the function (return `success: False`), not via signature
  defaults — defaults are usually `None` meaning "required".
- Destructive editor-session actions (e.g. `create_level`/`load_level` switch/replace the open
  level) are tested via guard paths only in-editor; the happy path can reset the TCP server.

### Optional-plugin dependencies (soft, never hard)

Python bindings for a plugin's classes only exist when that plugin is loaded, so a
plugin-dependent action is a **soft runtime dependency** — its absence breaks only that
action, never the rest. The convention:

- Guard at call time and return an actionable error:
  ```python
  if not hasattr(unreal, "IKRetargeterController"):
      return json.dumps({"success": False,
          "message": "Requires the IKRig plugin. Enable it in Edit > Plugins and restart."})
  ```
- Note the requirement in the docstring first line — `(requires the X plugin)` — so it
  shows up in `list_actions`.
- In-editor tests `skipTest` when the plugin isn't available.
- **Never** add a Build.cs / .uplugin dependency on an optional plugin for C++ helpers —
  that would make the whole plugin fail to load without it. Prefer the Python path; when
  C++ is unavoidable, put it in a companion plugin (below).
- Don't auto-enable plugins (editing .uproject is invasive and needs a restart) — the
  guard message tells the user what to enable.

### Companion plugins (when C++ needs a hard dependency)

Some editor APIs are simply not script-exposed, and no amount of reflection reaches them.
The StateTree editor API is the worked example: `UStateTreeEditingSubsystem` is
`UCLASS(MinimalAPI)` whose compile/validate methods are plain C++ statics with no
`UFUNCTION`, `UStateTreeState::Children` is `BlueprintReadOnly` with no `Edit` flag so
Python cannot append to it, and `UStateTreeEditorData::EditorBindings` is a bare
`UPROPERTY()`. Reading was possible through `MCPythonHelper.GetObjectPropertyRaw`;
writing was not.

The answer is a **separate plugin**, not a module inside UnrealMCPython and not an
`"Optional": true` reference. `Plugins/UnrealMCPythonStateTree/` is the template:

- `EnabledByDefault: false`, and a **hard** dependency on both `UnrealMCPython` and the
  optional plugin. Hard is safe precisely because the whole plugin is opt-in — a project
  that does not enable it never links the dependency.
- The dependency is contained. A hard dep inside the core plugin would force the optional
  plugin on every consumer project and take the entire MCP server down whenever it is
  disabled; that is the failure this structure exists to avoid.
- Module type `Editor` links an `UncookedOnly` editor module fine — `Editor` is the
  narrower of the two.
- The `ue_*` functions still live in the **core** plugin's `<domain>_actions.py`, so the
  catalog generator needs no change. They guard on the helper class instead of the plugin:
  ```python
  if not hasattr(unreal, "MCPythonStateTreeHelper"):
      return json.dumps({"success": False, "message":
          "Requires the UnrealMCPythonStateTree plugin. Enable it in Edit > Plugins, "
          "then rebuild the editor with it closed."})
  ```
- The core plugin's `Private/MCPythonHelperInternal.h` is not reachable from another
  module. Duplicate the few JSON helpers rather than promoting them to Public.
- Mutating actions mark the package dirty and stop there; `save` is an explicit opt-in
  param, so a failed authoring step never leaves a half-written asset on disk.
- `release.yml` stages `Plugins/UnrealMCPython` only, so a companion plugin ships in no
  release zip until that workflow is extended.
