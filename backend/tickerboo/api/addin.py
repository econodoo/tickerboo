"""
Office.js Excel Add-in — serves all add-in files dynamically.

The add-in files are auto-generated from the function registry,
so adding a new plugin = function immediately appears in Excel.

Endpoints:
  GET /addin/manifest.xml     → Office add-in manifest (for sideloading)
  GET /addin/functions.json   → Custom Functions metadata (auto-generated)
  GET /addin/functions.js     → Custom Functions JS runtime (auto-generated)
  GET /addin/taskpane         → Sidebar UI (function browser + quick test)
"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import Response, HTMLResponse

from tickerboo.functions.registry import registry
from tickerboo.config import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/addin", tags=["addin"])

# Stable add-in ID (generated once, stays forever)
ADDIN_ID = "b7f8c2a1-4e3d-4f5a-9b6c-8d7e0f1a2b3c"
ADDIN_VERSION = "1.0.0"


# ── Manifest ─────────────────────────────────────────────────────────────────

@router.get("/manifest.xml", response_class=Response)
async def manifest(request: Request):
    """Office add-in manifest for sideloading."""
    base = _get_base_url(request)
    xml = _build_manifest(base)
    return Response(content=xml, media_type="application/xml")


# ── Functions metadata (auto-generated) ──────────────────────────────────────

@router.get("/functions.json", response_class=Response)
async def functions_json():
    """Custom Functions metadata — auto-generated from plugin registry."""
    functions = []
    for fn in registry.list_all():
        params = []
        for p in fn["params"]:
            ptype = _map_param_type(p["type"])
            param = {
                "name": p["name"],
                "description": p.get("description", ""),
                "type": ptype,
            }
            if not p.get("required", False):
                param["optional"] = True
            params.append(param)

        result_type, dimensionality = _map_output_type(fn["output"])
        func = {
            "id": fn["name"],
            "name": fn["name"],
            "description": fn.get("description", ""),
            "parameters": params,
            "result": {"type": result_type, "dimensionality": dimensionality},
        }
        functions.append(func)

    metadata = {
        "allowCustomDataForDataTypeAny": True,
        "functions": functions,
    }
    return Response(
        content=json.dumps(metadata, indent=2),
        media_type="application/json",
    )


# ── Functions JS runtime ─────────────────────────────────────────────────────

@router.get("/functions.js", response_class=Response)
async def functions_js(request: Request):
    """Custom Functions JS — generic API dispatcher, auto-registered."""
    base = _get_base_url(request)
    all_fns = registry.list_all()

    # Build the registry object (function name → param names)
    reg_entries = {}
    for fn in all_fns:
        reg_entries[fn["name"]] = [p["name"] for p in fn["params"]]

    # Generate association calls
    associations = []
    for fn in all_fns:
        param_names = [p["name"] for p in fn["params"]]
        js_params = ", ".join(param_names)
        associations.append(
            f'  CustomFunctions.associate("TB.{fn["name"]}", ({js_params}) => '
            f'tb("{fn["name"]}", [{", ".join(param_names)}], {json.dumps(param_names)}));'
        )

    js_code = f"""/**
 * TickerBoo Custom Functions for Excel
 * Auto-generated — do not edit manually.
 * {len(all_fns)} functions registered.
 */

const TB_API = "{base}";
const TB_REGISTRY = {json.dumps(reg_entries)};

/**
 * Generic dispatcher — calls TickerBoo API for any function.
 */
async function tb(fnName, argValues, argNames) {{
  const args = {{}};
  argNames.forEach((name, i) => {{
    const v = argValues[i];
    if (v !== undefined && v !== null && v !== "") {{
      args[name] = v;
    }}
  }});

  try {{
    const resp = await fetch(`${{TB_API}}/call/${{fnName}}`, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ args }}),
    }});
    const data = await resp.json();

    if (data.status === "ok") {{
      const v = data.value;
      // Scalar → return directly
      if (v === null || v === undefined) return "";
      if (typeof v === "number" || typeof v === "string") return v;
      // 1D array → return as row (Excel spill)
      if (Array.isArray(v) && !Array.isArray(v[0])) return [v];
      // 2D array → return as grid (Excel spill)
      if (Array.isArray(v)) return v;
      // Object → JSON string
      return JSON.stringify(v);
    }}

    // Error → return message as string (shows in cell)
    return data.message || "#ERROR";
  }} catch (e) {{
    return "#CONN_ERROR";
  }}
}}

// ── Auto-register all functions ─────────────────────────────────────────
{chr(10).join(associations)}
"""
    return Response(content=js_code, media_type="application/javascript")


# ── Taskpane ─────────────────────────────────────────────────────────────────

@router.get("/taskpane", response_class=HTMLResponse)
async def taskpane(request: Request):
    """Excel sidebar UI — function browser, quick test, chart links."""
    from pathlib import Path
    html_path = Path(__file__).parent.parent / "static" / "addin" / "taskpane.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>Taskpane not built yet</h2>", status_code=404)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_base_url(request: Request) -> str:
    """Determine the API base URL from the request."""
    # In production behind nginx with root_path="/tb"
    if settings.env == "prod":
        return "https://tmc.vetami.net/tb"
    # Dev: use request's base
    return str(request.base_url).rstrip("/")


def _map_param_type(t: str) -> str:
    """Map our param type to Office.js type."""
    return {"string": "string", "number": "number", "integer": "number",
            "date": "string", "boolean": "boolean"}.get(t, "string")


def _map_output_type(output: str) -> tuple[str, str]:
    """Map our output type to Office.js result type + dimensionality."""
    if output == "scalar":
        return "number", "scalar"
    elif output == "array":
        return "any", "matrix"
    elif output == "text":
        return "string", "scalar"
    return "any", "scalar"


def _build_manifest(base: str) -> str:
    """Build the Office add-in manifest XML."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<OfficeApp
  xmlns="http://schemas.microsoft.com/office/appforoffice/1.1"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:bt="http://schemas.microsoft.com/office/officeappbasictypes/1.0"
  xmlns:ov="http://schemas.microsoft.com/office/taskpaneappversionoverrides"
  xsi:type="TaskPaneApp">

  <Id>{ADDIN_ID}</Id>
  <Version>{ADDIN_VERSION}</Version>
  <ProviderName>TickerBoo</ProviderName>
  <DefaultLocale>en-US</DefaultLocale>
  <DisplayName DefaultValue="TickerBoo"/>
  <Description DefaultValue="VN Stock Market Data &amp; Analytics — 65+ TB.* functions for Excel"/>
  <IconUrl DefaultValue="{base}/static/icon-32.png"/>
  <HighResolutionIconUrl DefaultValue="{base}/static/icon-64.png"/>
  <SupportUrl DefaultValue="https://github.com/econodoo/tickerboo"/>

  <Hosts>
    <Host Name="Workbook"/>
  </Hosts>

  <DefaultSettings>
    <SourceLocation DefaultValue="{base}/addin/taskpane"/>
  </DefaultSettings>

  <Permissions>ReadWriteDocument</Permissions>

  <VersionOverrides xmlns="http://schemas.microsoft.com/office/taskpaneappversionoverrides" xsi:type="VersionOverridesV1_0">
    <Hosts>
      <Host xsi:type="Workbook">
        <AllFormFactors>
          <ExtensionPoint xsi:type="CustomFunctions">
            <Script>
              <SourceLocation resid="Functions.Script.Url"/>
            </Script>
            <Page>
              <SourceLocation resid="Functions.Page.Url"/>
            </Page>
            <Metadata>
              <SourceLocation resid="Functions.Metadata.Url"/>
            </Metadata>
            <Namespace resid="Functions.Namespace"/>
          </ExtensionPoint>
        </AllFormFactors>
        <DesktopFormFactor>
          <GetStarted>
            <Title resid="GetStarted.Title"/>
            <Description resid="GetStarted.Description"/>
            <LearnMoreUrl resid="GetStarted.LearnMoreUrl"/>
          </GetStarted>
          <FunctionFile resid="Commands.Url"/>
          <ExtensionPoint xsi:type="PrimaryCommandSurface">
            <OfficeTab id="TabHome">
              <Group id="CommandsGroup">
                <Label resid="CommandsGroup.Label"/>
                <Icon>
                  <bt:Image size="16" resid="Icon.16x16"/>
                  <bt:Image size="32" resid="Icon.32x32"/>
                  <bt:Image size="80" resid="Icon.80x80"/>
                </Icon>
                <Control xsi:type="Button" id="TaskpaneButton">
                  <Label resid="TaskpaneButton.Label"/>
                  <Supertip>
                    <Title resid="TaskpaneButton.Label"/>
                    <Description resid="TaskpaneButton.Tooltip"/>
                  </Supertip>
                  <Icon>
                    <bt:Image size="16" resid="Icon.16x16"/>
                    <bt:Image size="32" resid="Icon.32x32"/>
                    <bt:Image size="80" resid="Icon.80x80"/>
                  </Icon>
                  <Action xsi:type="ShowTaskpane">
                    <TaskpaneId>ButtonId1</TaskpaneId>
                    <SourceLocation resid="Taskpane.Url"/>
                  </Action>
                </Control>
              </Group>
            </OfficeTab>
          </ExtensionPoint>
        </DesktopFormFactor>
      </Host>
    </Hosts>

    <Resources>
      <bt:Images>
        <bt:Image id="Icon.16x16" DefaultValue="{base}/static/icon-16.png"/>
        <bt:Image id="Icon.32x32" DefaultValue="{base}/static/icon-32.png"/>
        <bt:Image id="Icon.80x80" DefaultValue="{base}/static/icon-80.png"/>
      </bt:Images>
      <bt:Urls>
        <bt:Url id="Functions.Script.Url" DefaultValue="{base}/addin/functions.js"/>
        <bt:Url id="Functions.Metadata.Url" DefaultValue="{base}/addin/functions.json"/>
        <bt:Url id="Functions.Page.Url" DefaultValue="{base}/addin/taskpane"/>
        <bt:Url id="Taskpane.Url" DefaultValue="{base}/addin/taskpane"/>
        <bt:Url id="Commands.Url" DefaultValue="{base}/addin/taskpane"/>
        <bt:Url id="GetStarted.LearnMoreUrl" DefaultValue="https://github.com/econodoo/tickerboo"/>
      </bt:Urls>
      <bt:ShortStrings>
        <bt:String id="Functions.Namespace" DefaultValue="TB"/>
        <bt:String id="GetStarted.Title" DefaultValue="TickerBoo is ready!"/>
        <bt:String id="CommandsGroup.Label" DefaultValue="TickerBoo"/>
        <bt:String id="TaskpaneButton.Label" DefaultValue="TickerBoo"/>
      </bt:ShortStrings>
      <bt:LongStrings>
        <bt:String id="GetStarted.Description" DefaultValue="Type =TB.PRICE(&quot;VNM&quot;) in any cell to get started."/>
        <bt:String id="TaskpaneButton.Tooltip" DefaultValue="Open TickerBoo sidebar — browse functions, test formulas, open charts"/>
      </bt:LongStrings>
    </Resources>
  </VersionOverrides>
</OfficeApp>"""
