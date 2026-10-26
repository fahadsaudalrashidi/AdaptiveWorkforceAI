"""Browser-level sign-in, navigation, and upload coverage using local Chromium."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "inventory_snapshot_only_test_data.csv"
APP_URL = "http://127.0.0.1:5175"


class DevTools:
    def __init__(self, websocket_url: str) -> None:
        self.websocket_url = websocket_url
        self.socket = None
        self.pending: dict[int, asyncio.Future] = {}
        self.listeners: dict[str, list] = {}
        self.next_id = 0
        self.reader: asyncio.Task | None = None

    async def start(self) -> None:
        self.socket = await connect(self.websocket_url)
        self.reader = asyncio.create_task(self._read_messages())

    async def _read_messages(self) -> None:
        assert self.socket is not None
        async for raw in self.socket:
            message = json.loads(raw)
            if "id" in message:
                future = self.pending.pop(message["id"], None)
                if future and not future.done():
                    if "error" in message:
                        future.set_exception(RuntimeError(message["error"]["message"]))
                    else:
                        future.set_result(message.get("result", {}))
                continue
            for listener in self.listeners.get(message.get("method", ""), []):
                asyncio.create_task(listener(message.get("params", {})))

    def on(self, method: str, listener) -> None:
        self.listeners.setdefault(method, []).append(listener)

    async def send(self, method: str, params: dict | None = None) -> dict:
        assert self.socket is not None
        self.next_id += 1
        future = asyncio.get_running_loop().create_future()
        self.pending[self.next_id] = future
        await self.socket.send(
            json.dumps({"id": self.next_id, "method": method, "params": params or {}})
        )
        return await future

    async def evaluate(self, expression: str):
        result = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
        )
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            description = details.get("exception", {}).get("description")
            raise AssertionError(description or details.get("text", "Browser evaluation failed"))
        return result.get("result", {}).get("value")

    async def close(self) -> None:
        if self.socket:
            await self.socket.close()
        if self.reader:
            await asyncio.gather(self.reader, return_exceptions=True)


async def wait_for(condition, description: str, timeout: float = 12) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await condition():
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {description}")


async def read_devtools_url(stderr: asyncio.StreamReader) -> str:
    while True:
        line = await asyncio.wait_for(stderr.readline(), timeout=10)
        if not line:
            raise AssertionError("Chromium exited before opening its DevTools endpoint")
        match = re.search(rb"DevTools listening on (ws://\S+)", line)
        if match:
            return match.group(1).decode()


def create_target(debug_url: str) -> dict:
    from urllib.parse import quote, urlsplit

    address = urlsplit(debug_url)
    request = Request(
        f"http://{address.netloc}/json/new?{quote(APP_URL, safe='')}",
        method="PUT",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read())


async def run_browser_regression() -> None:
    chromium_path = os.environ.get("CHROMIUM_PATH") or shutil.which("chromium")
    if not chromium_path:
        raise RuntimeError("Chromium is required (set CHROMIUM_PATH if it is not on PATH)")
    if not FIXTURE.is_file():
        raise FileNotFoundError(f"Missing CSV upload fixture: {FIXTURE.name}")

    profile = tempfile.mkdtemp(prefix="awi-chromium-")
    server = await asyncio.create_subprocess_exec(
        "npm",
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "5175",
        "--strictPort",
        cwd=ROOT / "executive-ui",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    browser = None
    cdp = None

    try:
        async def server_ready() -> bool:
            if server.returncode is not None:
                raise AssertionError("Vite exited before becoming ready")
            try:
                with urlopen(APP_URL, timeout=1) as response:
                    return response.status == 200
            except Exception:
                return False

        await wait_for(server_ready, "Vite development server")
        browser = await asyncio.create_subprocess_exec(
            chromium_path,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            "about:blank",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        assert browser.stderr is not None
        target = create_target(await read_devtools_url(browser.stderr))
        cdp = DevTools(target["webSocketDebuggerUrl"])
        await cdp.start()
        await cdp.send("Page.enable")
        await cdp.send("Runtime.enable")
        await cdp.send("DOM.enable")
        await cdp.send(
            "Fetch.enable",
            {
                "patterns": [
                    {"urlPattern": "*/api/auth/login", "requestStage": "Request"},
                    {
                        "urlPattern": "*/api/local/inventory-intelligence",
                        "requestStage": "Request",
                    },
                ]
            },
        )

        observed = {"login": False, "upload": None}
        inventory_result = {
            "filename": FIXTURE.name,
            "row_count": 4,
            "inventory_intelligence": {
                "stock_levels": {
                    "available": True,
                    "reason": None,
                    "columns_detected": {"sku": True, "quantity_on_hand": True},
                    "has_movement_history": False,
                    "n_items": 1,
                    "items": [
                        {
                            "sku": "SKU-TEST",
                            "item_name": "Regression item",
                            "category": "Test",
                            "current_stock": 12,
                            "current_stock_source": "snapshot_column",
                            "total_received": None,
                            "total_issued": None,
                            "last_movement_date": None,
                        }
                    ],
                    "narrative_en": "Inventory upload regression result.",
                    "narrative_ar": "نتيجة اختبار تحميل المخزون.",
                },
                "turnover": {
                    "available": False,
                    "reason": "No movement history.",
                    "columns_detected": {},
                    "formula_used": None,
                    "items": [],
                    "narrative_en": "",
                    "narrative_ar": "",
                },
                "stock_aging": {
                    "available": False,
                    "reason": "No movement history.",
                    "columns_detected": {},
                    "as_of_date": None,
                    "tier_counts": {},
                    "items": [],
                    "narrative_en": "",
                    "narrative_ar": "",
                },
                "abc_analysis": {
                    "available": False,
                    "reason": "No cost values.",
                    "columns_detected": {},
                    "total_value": None,
                    "tier_counts": {},
                    "tier_value_pct": {},
                    "items": [],
                    "narrative_en": "",
                    "narrative_ar": "",
                },
                "reorder_points": {
                    "available": False,
                    "reason": "No movement history.",
                    "columns_detected": {},
                    "z_service_level": 1.65,
                    "stockout_days_threshold": 7,
                    "overstock_days_threshold": 90,
                    "overstock_multiple": 2,
                    "items": [],
                    "narrative_en": "",
                    "narrative_ar": "",
                },
                "overstock_stockout": {
                    "available": False,
                    "reason": "No movement history.",
                    "n_stockout_risk": 0,
                    "n_overstock": 0,
                    "stockout_items": [],
                    "overstock_items": [],
                    "narrative_en": "",
                    "narrative_ar": "",
                },
                "disclaimer_en": "",
                "disclaimer_ar": "",
                "sources": [],
            },
        }

        async def fulfill(event: dict, payload: dict) -> None:
            await cdp.send(
                "Fetch.fulfillRequest",
                {
                    "requestId": event["requestId"],
                    "responseCode": 200,
                    "responseHeaders": [
                        {"name": "Content-Type", "value": "application/json"}
                    ],
                    "body": base64.b64encode(json.dumps(payload).encode()).decode(),
                },
            )

        async def handle_request(event: dict) -> None:
            from urllib.parse import urlsplit

            request = event["request"]
            path = urlsplit(request["url"]).path
            if path == "/api/auth/login":
                observed["login"] = True
                await fulfill(
                    event,
                    {
                        "access_token": "browser-test-access-token",
                        "refresh_token": "browser-test-refresh-token",
                        "user": {
                            "user_id": "browser-test-user",
                            "username": "browser-test",
                            "display_name": "Browser Regression",
                            "email": "browser@example.invalid",
                            "role": "hr_manager",
                            "must_change_password": False,
                        },
                    },
                )
            elif path == "/api/local/inventory-intelligence":
                observed["upload"] = request
                await fulfill(event, inventory_result)

        cdp.on("Fetch.requestPaused", handle_request)
        await cdp.send("Page.navigate", {"url": APP_URL})
        await wait_for(
            lambda: async_text_includes(cdp, "Sign in to THRIVE"),
            "sign-in page",
        )
        await cdp.evaluate("document.querySelector('button[title=\"Switch to Arabic\"]').click()")
        await wait_for(lambda: async_text_includes(cdp, "تسجيل الدخول إلى ثرايف"), "Arabic sign-in")
        await cdp.send("Emulation.setDeviceMetricsOverride", {
            "width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True,
        })
        await cdp.evaluate("document.fonts.ready")
        assert await cdp.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        image = await cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 80})
        output = ROOT / "generated-artifacts/thrive-ui/login-mobile-ar.jpg"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(base64.b64decode(image["data"]))
        await cdp.evaluate("document.querySelector('button[title=\"التبديل إلى الإنجليزية\"]').click()")
        await cdp.send("Emulation.setDeviceMetricsOverride", {
            "width": 1440, "height": 1050, "deviceScaleFactor": 1, "mobile": False,
        })

        await cdp.evaluate(
            """(() => {
              const set = (input, value) => {
                const setter = Object.getOwnPropertyDescriptor(
                  HTMLInputElement.prototype, 'value'
                ).set
                setter.call(input, value)
                input.dispatchEvent(new Event('input', { bubbles: true }))
                input.dispatchEvent(new Event('change', { bubbles: true }))
              }
              set(document.querySelector('input[autocomplete="username"]'), 'browser-test')
              set(document.querySelector('input[autocomplete="current-password"]'), 'BrowserTest!2026')
              document.querySelector('form button').click()
            })()"""
        )
        await wait_for(
            lambda: async_text_includes(
                cdp, "THRIVE Enterprise Intelligence"
            ),
            "signed-in overview",
        )
        assert observed["login"], "Sign-in should submit to the auth route"

        navigated = await cdp.evaluate(
            """(() => {
              const button = [...document.querySelectorAll('button')]
                .find(item => item.innerText.includes('Inventory Intelligence'))
              if (!button) return false
              button.click()
              return true
            })()"""
        )
        assert navigated, "Overview should expose inventory navigation"
        await wait_for(
            lambda: async_text_includes(cdp, "Upload an inventory snapshot"),
            "inventory upload page",
        )

        document = await cdp.send("DOM.getDocument", {"depth": -1})
        file_input = await cdp.send(
            "DOM.querySelector",
            {"nodeId": document["root"]["nodeId"], "selector": 'input[type="file"]'},
        )
        assert file_input.get("nodeId"), "Inventory page should expose a file input"
        await cdp.send(
            "DOM.setFileInputFiles",
            {"nodeId": file_input["nodeId"], "files": [str(FIXTURE)]},
        )

        await wait_for(lambda: asyncio.sleep(0, result=bool(observed["upload"])), "upload request")
        upload = observed["upload"]
        assert upload["method"] == "POST"
        assert upload["url"].endswith("/api/local/inventory-intelligence")
        authorization = next(
            (
                value
                for name, value in upload["headers"].items()
                if name.lower() == "authorization"
            ),
            None,
        )
        assert authorization == "Bearer browser-test-access-token", upload["headers"]
        await wait_for(
            lambda: async_text_includes(cdp, FIXTURE.name),
            "successful upload result",
        )
        page_text = await cdp.evaluate("document.body.innerText")
        assert "Regression item" in page_text
        assert "Inventory upload regression result." in page_text
        print("Frontend regression passed: sign-in, module navigation, and CSV upload/result.")
    finally:
        if cdp:
            await cdp.close()
        for process in (browser, server):
            if process and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
        shutil.rmtree(profile, ignore_errors=True)


async def async_text_includes(cdp: DevTools, expected: str) -> bool:
    text = await cdp.evaluate("document.body?.innerText ?? ''")
    return expected in (text or "")


if __name__ == "__main__":
    asyncio.run(run_browser_regression())
