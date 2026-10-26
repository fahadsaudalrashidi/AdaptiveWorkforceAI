"""Check the applied-filter UI against a running frontend using browser-only mocks.

Run: python tests/filtered_query_frontend_regression.py
The mock answer is produced by the real local engine; app auth stays intact.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlsplit

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import frontend_regression as browser_helpers
from backend.core.ai_business_analyst_engine import answer_question, analyst_answer_to_dict

APP_URL = os.environ.get("AWI_BROWSER_TEST_URL", "http://127.0.0.1:5000")
QUESTION = 'compare total "Sales" where "Region" = "West" versus "Region" = "East"'


async def main():
    frame = pd.DataFrame({"Sales": [10, 20, None, 40], "Region": ["West", "East", "West", None]})
    answer = analyst_answer_to_dict(answer_question(
        QUESTION, {}, use_llm=False, uploaded_frames={"sales.csv": frame},
    ))
    payload = {
        "mode": "local_fallback", "answer": {**answer, "actions_taken": []},
        "cloud_status": {"configured": False, "valid": False, "detail": "Offline"},
        "files_generated": [], "files_ingested": ["sales.csv"],
        "domains_detected": [], "file_details": [],
    }
    browser_helpers.APP_URL = APP_URL
    observations = {"request": None}
    with tempfile.TemporaryDirectory(prefix="awi-filters-browser-") as directory:
        fixture = Path(directory, "sales.csv")
        frame.to_csv(fixture, index=False)
        browser = await asyncio.create_subprocess_exec(
            shutil.which("chromium"), "--headless=new", "--no-sandbox",
            "--disable-gpu", "--disable-dev-shm-usage", "--remote-debugging-port=0",
            f"--user-data-dir={directory}/profile", "about:blank",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        cdp = None
        try:
            target = browser_helpers.create_target(await browser_helpers.read_devtools_url(browser.stderr))
            cdp = browser_helpers.DevTools(target["webSocketDebuggerUrl"])
            await cdp.start()
            for domain in ("Page", "Runtime", "DOM"):
                await cdp.send(domain + ".enable")
            await cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source":
                "sessionStorage.setItem('awi_access_token','browser-test-only');"})

            async def handle_request(event):
                path = urlsplit(event["request"]["url"]).path
                body = {}
                if path == "/api/auth/me":
                    body = {"user_id": "browser-test", "username": "browser-test",
                            "display_name": "Browser Test", "email": "",
                            "role": "system_admin", "must_change_password": False}
                elif path.endswith("/agentic/status"):
                    body = {"cloud_configured": False, "cloud_valid": False,
                            "cloud_detail": "Offline", "tools_available": []}
                elif path.endswith("/registry"):
                    body = {"registry": [], "ollama_reachable": False, "ollama_model": ""}
                elif path == "/api/local/ai-business-analyst/agentic":
                    observations["request"] = event["request"]
                    body = payload
                await cdp.send("Fetch.fulfillRequest", {
                    "requestId": event["requestId"], "responseCode": 200,
                    "responseHeaders": [{"name": "Content-Type", "value": "application/json"}],
                    "body": base64.b64encode(json.dumps(body).encode()).decode(),
                })

            cdp.on("Fetch.requestPaused", handle_request)
            await cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*/api/*"}]})
            await cdp.send("Page.navigate", {"url": APP_URL})

            async def contains(text):
                return await cdp.evaluate(f"document.body?.innerText.includes({json.dumps(text)}) ?? false")

            await browser_helpers.wait_for(lambda: contains("AI Business Analyst"), "analyst navigation")
            await cdp.evaluate("""Array.from(document.querySelectorAll('button')).find(
                b => b.textContent.includes('AI Business Analyst')).click()""")
            await browser_helpers.wait_for(
                lambda: cdp.evaluate("!!document.querySelector('input[type=file]')"), "upload control")
            assert await contains('Dates must be YYYY-MM-DD')
            document = await cdp.send("DOM.getDocument")
            node = await cdp.send("DOM.querySelector", {
                "nodeId": document["root"]["nodeId"], "selector": "input[type=file]",
            })
            await cdp.send("DOM.setFileInputFiles", {"nodeId": node["nodeId"], "files": [str(fixture)]})
            await cdp.evaluate("""(() => {
                const input = document.querySelector('input[placeholder]')
                Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input, %s)
                input.dispatchEvent(new Event('input',{bubbles:true}))
            })()""" % json.dumps(QUESTION))
            await cdp.evaluate("document.querySelector('svg.lucide-send').closest('button').click()")
            await browser_helpers.wait_for(lambda: contains("Applied filters"), "applied filters summary")
            summary = await cdp.evaluate("document.querySelector('section[aria-label=\"Applied filters\"]').innerText")
            for expected in ['Source: sales.csv', 'Cohort 1', 'Cohort 2', 'Region = "West"',
                             'Region = "East"', 'Included: 1 / 4', 'Excluded: 3',
                             'Missing filter values (source rows): 1',
                             'Missing measure values (matched rows): 1',
                             'Missing measure values (matched rows): 0',
                             'Cohorts may overlap']:
                assert expected in summary, (expected, summary)
            assert await contains("Difference (cohort 1 minus cohort 2): -10.00")
            request = observations["request"]
            assert request
            assert "authorization" in {key.lower() for key in request["headers"]}
            assert '"use_cloud"\r\n\r\nfalse' in request.get("postData", "")
            await cdp.send("Emulation.setDeviceMetricsOverride", {
                "width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True,
            })
            assert await cdp.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
            ), "Filter summary overflows the mobile viewport"
            print("PASS: comparison filters, both cohorts, row/missing-value counts, source, mobile width, and local-only request.")
        finally:
            if cdp:
                await cdp.close()
            browser.terminate()
            await browser.wait()


if __name__ == "__main__":
    asyncio.run(main())
