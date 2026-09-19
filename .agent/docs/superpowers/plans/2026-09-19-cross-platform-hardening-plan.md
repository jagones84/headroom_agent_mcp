# Cross-Platform Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `headroom_agent_mcp` generic, configurable, and runnable on both Windows and Linux/DGX hosts without hardcoded DGX-only assumptions.

**Architecture:** Keep one Python MCP core and add thin host launchers that only bootstrap env and start the same module. Keep Headroom proxy optional via env, update example configs/docs to be portable, and prove the behavior with focused tests.

**Tech Stack:** Python 3.11+, Pydantic v2, FastMCP, pytest, Bash, Windows batch/PowerShell-compatible launching.

---

## File Map

- Modify: `src/headroom_agent_mcp/config.py`
- Modify: `src/headroom_agent_mcp/server.py`
- Modify: `README.md`
- Modify: `.env.template`
- Modify: `config/openclaw.headroom_agent_mcp.example.json`
- Modify: `scripts/openclaw_stdio_dgx.sh`
- Create: `scripts/headroom_agent_stdio_windows.cmd`
- Create: `config/windows.stdio.headroom_agent_mcp.example.json`
- Test: `tests/test_llm_config.py`
- Test: `tests/test_server_smoke.py`

### Task 1: Add Portable Windows Launcher

**Files:**
- Create: `scripts/headroom_agent_stdio_windows.cmd`
- Test: `tests/test_server_smoke.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

def test_windows_stdio_launcher_exists_and_targets_module() -> None:
    launcher = Path("scripts/headroom_agent_stdio_windows.cmd")
    content = launcher.read_text(encoding="utf-8")
    assert "PYTHONPATH" in content
    assert "headroom_agent_mcp.server" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_server_smoke.py -q`
Expected: FAIL because the Windows launcher file does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```bat
@echo off
setlocal
set "ROOT_DIR=%~dp0.."
if exist "%ROOT_DIR%\.env" (
  for /f "usebackq tokens=1,* delims==" %%A in ("%ROOT_DIR%\.env") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)
set "PYTHONPATH=%ROOT_DIR%\src"
python -m headroom_agent_mcp.server
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_server_smoke.py -q`
Expected: PASS for the new launcher assertion.

- [ ] **Step 5: Commit**

```bash
git add scripts/headroom_agent_stdio_windows.cmd tests/test_server_smoke.py
git commit -m "feat: add windows stdio launcher"
```

### Task 2: Make Config Explicitly Cross-Platform

**Files:**
- Modify: `src/headroom_agent_mcp/config.py`
- Modify: `.env.template`
- Test: `tests/test_llm_config.py`

- [ ] **Step 1: Write the failing test**

```python
def test_config_uses_cross_platform_defaults(tmp_path: Path) -> None:
    config = HeadroomAgentConfig.from_sources(tmp_path / "missing.yaml")
    assert config.llm_profiles["openrouter"].model == "deepseek/deepseek-v4-flash"
    assert config.default_model_profile == "openrouter"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_llm_config.py -q`
Expected: FAIL if defaults/docs still drift or if the config shape is incomplete.

- [ ] **Step 3: Write minimal implementation**

```python
provider = os.getenv("HEADROOM_AGENT_MODEL_PROVIDER", "openrouter")
model = os.getenv("HEADROOM_AGENT_MODEL_NAME", "deepseek/deepseek-v4-flash")
...
return cls(..., default_model_profile=provider if provider in profiles else None)
```

Also align `.env.template` with the same slug model id.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_llm_config.py -q`
Expected: PASS and no config regression.

- [ ] **Step 5: Commit**

```bash
git add src/headroom_agent_mcp/config.py .env.template tests/test_llm_config.py
git commit -m "fix: align cross-platform config defaults"
```

### Task 3: Add Host Example Configs

**Files:**
- Modify: `config/openclaw.headroom_agent_mcp.example.json`
- Create: `config/windows.stdio.headroom_agent_mcp.example.json`
- Modify: `README.md`

- [ ] **Step 1: Write the failing test**

```python
def test_windows_example_config_exists() -> None:
    path = Path("config/windows.stdio.headroom_agent_mcp.example.json")
    assert path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_server_smoke.py -q`
Expected: FAIL because the Windows example config file does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```json
{
  "mcpServers": {
    "headroom_agent_discovery": {
      "type": "STDIO",
      "command": "Z:\\Repositories\\headroom_agent_mcp\\scripts\\headroom_agent_stdio_windows.cmd",
      "args": []
    }
  }
}
```

Also keep the OpenClaw Linux example on the shell wrapper path and update README to mention both host examples explicitly.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_server_smoke.py -q`
Expected: PASS for the new example-config assertion.

- [ ] **Step 5: Commit**

```bash
git add config/openclaw.headroom_agent_mcp.example.json config/windows.stdio.headroom_agent_mcp.example.json README.md tests/test_server_smoke.py
git commit -m "docs: add cross-platform host examples"
```

### Task 4: Verify Whole Cross-Platform Slice

**Files:**
- Modify: `.agent/HANDOFF.md`
- Test: `tests/test_llm_config.py`
- Test: `tests/test_server_smoke.py`

- [ ] **Step 1: Write/extend the final verification checks**

```python
def test_create_server_returns_fastmcp_instance() -> None:
    server = create_server()
    assert server.name == "headroom_agent_mcp"
```

Keep or extend the smoke tests so they verify:
- Windows launcher exists and points to the module
- Windows example config exists
- config defaults remain portable

- [ ] **Step 2: Run focused tests**

Run: `python -m pytest tests/test_llm_config.py tests/test_server_smoke.py -q`
Expected: PASS

- [ ] **Step 3: Run full suite**

Run: `python -m pytest tests -q`
Expected: PASS with no regressions.

- [ ] **Step 4: Update operational docs**

```md
- Windows launcher added: `scripts/headroom_agent_stdio_windows.cmd`
- Windows example config added: `config/windows.stdio.headroom_agent_mcp.example.json`
- Linux/DGX wrapper kept: `scripts/openclaw_stdio_dgx.sh`
```

- [ ] **Step 5: Commit**

```bash
git add .agent/HANDOFF.md tests/test_llm_config.py tests/test_server_smoke.py
git commit -m "test: verify cross-platform hardening"
```

---

## Self-Review

- Spec coverage: Windows launcher, portable config, platform examples, docs, and test verification are all mapped to tasks.
- Placeholder scan: no `TODO`/`TBD`; each task has exact files, commands, and expected outcomes.
- Type consistency: launcher names, config filenames, and model id are consistent across tasks.
