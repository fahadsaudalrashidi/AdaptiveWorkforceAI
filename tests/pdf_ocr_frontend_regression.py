"""OCR UI interaction check against a running frontend, using browser-only mocks.

Run: python tests/pdf_ocr_frontend_regression.py
Uses system Chromium and websockets, as does frontend_regression.py.
Authentication is NOT changed in the application or server.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import frontend_regression as browser_helpers
from backend.tests.test_local_pdf_ocr import LocalPdfOcrTests, no_network

ROOT = Path(__file__).resolve().parents[1]
APP_URL = os.environ.get("AWI_BROWSER_TEST_URL", "http://127.0.0.1:5000")


async def main():
    # Build the mocked UI response through the actual governed, offline API.
    case = LocalPdfOcrTests()
    client, _ = case.client()
    filename = "scanned_low_quality.pdf"
    with no_network(), client:
        response = client.post(
            "/api/local/ai-business-analyst/agentic", data={"question": "Total revenue"},
            files={"files": (filename, case.raw(filename), "application/pdf")},
        )
        assert response.status_code == 200, response.text
        answer = response.json()
        review = [{
            "source_id": answer["file_details"][0]["source_id"],
            "scope": "reviewed_rows_only", "confirmed_headers": True, "columns": ["Category", "Revenue"],
            "rows": [
                {"page": 1, "values": ["Retail", "125"], "verified": True},
                {"page": 1, "values": ["Online", "75"], "verified": True},
            ],
        }]
        reviewed = client.post(
            "/api/local/ai-business-analyst/agentic",
            data={"question": "Total revenue", "reviewed_tables": json.dumps(review)},
            files={"files": (filename, case.raw(filename), "application/pdf")},
        )
        assert reviewed.status_code == 200, reviewed.text
    assert response.status_code == 200, response.text
    browser_helpers.APP_URL = APP_URL
    observations = {"polls": 0, "request": None}
    with tempfile.TemporaryDirectory(prefix="awi-ocr-browser-") as profile:
        browser = await asyncio.create_subprocess_exec(
            shutil.which("chromium"), "--headless=new", "--no-sandbox",
            "--disable-gpu", "--disable-dev-shm-usage", "--remote-debugging-port=0",
            f"--user-data-dir={profile}", "about:blank",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        cdp = None
        try:
            target = browser_helpers.create_target(await browser_helpers.read_devtools_url(browser.stderr))
            cdp = browser_helpers.DevTools(target["webSocketDebuggerUrl"])
            await cdp.start()
            for domain in ("Page", "Runtime", "DOM"):
                await cdp.send(domain + ".enable")
            await cdp.send("Emulation.setDeviceMetricsOverride", {
                "width": 1440, "height": 1050, "deviceScaleFactor": 1, "mobile": False,
            })
            # Install below the application's authenticated-fetch wrapper.
            # Stream fragments are browser-only fixtures, never shipped code.
            script = "sessionStorage.setItem('awi_access_token','browser-test-only');window.__answers=" + json.dumps([answer, reviewed.json()]) + ";window.__fixtureFilename=" + json.dumps(filename) + r""";
            window.__requests = [];
            const originalFetch = window.fetch.bind(window);
            window.fetch = async (input, init) => {
              if (String(input).endsWith('/ai-business-analyst/agentic/stream')) {
                const index = window.__requests.length;
                window.__requests.push({
                  authenticated: new Headers(init.headers).has('Authorization'),
                  question: init.body.get('question'), cloud: init.body.get('use_cloud'),
                  reviewed: init.body.get('reviewed_tables')
                });
                const encoder = new TextEncoder();
                const stream = new ReadableStream({start(controller) {
                  controller.enqueue(encoder.encode('event: progress\ndata: ' + JSON.stringify({stage:'parsing',filename:window.__fixtureFilename}) + '\n\n'));
                  setTimeout(() => controller.enqueue(encoder.encode('event: progress\ndata: {"stage":"extracting","page":1,"total_pages":1,"method":"ocr"}\n\n')), 50);
                  window.__releaseAnalysis = () => {
                    const bytes = encoder.encode('event: result\ndata: ' + JSON.stringify(window.__answers[index]) + '\n\n');
                    controller.enqueue(bytes.slice(0, 31));
                    controller.enqueue(bytes.slice(31));
                    controller.close();
                  };
                }});
                return new Response(stream,{headers:{'Content-Type':'text/event-stream'}});
              }
              return originalFetch(input,init);
            };
            window.__setInput = (input,value) => {
              Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);
              input.dispatchEvent(new Event('input',{bubbles:true}));
            };
            """
            await cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": script})

            async def fulfill(event, payload):
                await cdp.send("Fetch.fulfillRequest", {
                    "requestId": event["requestId"], "responseCode": 200,
                    "responseHeaders": [{"name": "Content-Type", "value": "application/json"}],
                    "body": base64.b64encode(json.dumps(payload).encode()).decode(),
                })

            async def handle_request(event):
                path = urlsplit(event["request"]["url"]).path
                if path == "/api/auth/me":
                    await fulfill(event, {
                        "user_id": "browser-test", "username": "browser-test",
                        "display_name": "Browser Test", "email": "",
                        "role": "system_admin", "must_change_password": False,
                    })
                elif "/ocr-progress/" in path:
                    observations["polls"] += 1
                    await fulfill(event, {"stage": "extracting", "filename": "scan.pdf",
                                          "page": 1, "total_pages": 1, "method": "ocr"})
                elif path.endswith("/agentic/status"):
                    await fulfill(event, {"cloud_configured": False, "cloud_valid": False,
                                          "cloud_detail": "Offline", "tools_available": [], "streaming_supported": True})
                elif path.endswith("/registry"):
                    await fulfill(event, {"registry": [], "ollama_reachable": False, "ollama_model": ""})
                else:
                    await fulfill(event, {})

            cdp.on("Fetch.requestPaused", handle_request)
            await cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*/api/*"}]})
            await cdp.send("Page.navigate", {"url": APP_URL})

            async def text_contains(text):
                return await cdp.evaluate(f"document.body?.innerText.includes({json.dumps(text)}) ?? false")

            await browser_helpers.wait_for(lambda: text_contains("AI Business Analyst"), "analyst navigation")
            assert await cdp.evaluate("document.querySelectorAll('img[src*=\"thrive-logo\"]').length >= 2")
            await cdp.evaluate("document.fonts.ready")
            await asyncio.sleep(1)
            out = ROOT / "generated-artifacts/thrive-ui"
            out.mkdir(parents=True, exist_ok=True)

            async def screenshot(name):
                image = await cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 80})
                (out / name).write_bytes(base64.b64decode(image["data"]))

            await screenshot("dashboard-en.jpg")
            await cdp.evaluate("""Array.from(document.querySelectorAll('button')).find(
                b => b.textContent.includes('AI Business Analyst')).click()""")
            await browser_helpers.wait_for(
                lambda: cdp.evaluate("!!document.querySelector('input[type=file]')"), "upload control")
            document = await cdp.send("DOM.getDocument")
            node = await cdp.send("DOM.querySelector", {
                "nodeId": document["root"]["nodeId"], "selector": "input[type=file]",
            })
            await cdp.send("DOM.setFileInputFiles", {
                "nodeId": node["nodeId"],
                "files": [str(ROOT / "backend/tests/fixtures/pdf_ocr/scanned_low_quality.pdf")],
            })
            await cdp.evaluate("""(() => {
                const input = document.querySelector('input[placeholder]')
                Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'Total revenue')
                input.dispatchEvent(new Event('input',{bubbles:true}))
            })()""")
            await cdp.evaluate("document.querySelector('svg.lucide-send').closest('button').click()")
            await browser_helpers.wait_for(lambda: text_contains("Page 1 of 1"), "real page progress")
            assert observations["polls"] == 0, "Live progress must not depend on polling another worker"
            await cdp.evaluate("window.__releaseAnalysis()")
            await browser_helpers.wait_for(lambda: text_contains("uncertain numeric tokens"), "uncertain figures")
            for expected in ("Offline OCR languages", "ara+eng", "No paid API used", "human review", "87.6%"):
                assert await text_contains(expected), expected
            assert await cdp.evaluate("window.__requests[0].authenticated")
            await cdp.evaluate("""Array.from(document.querySelectorAll('button')).find(
                b => b.textContent.includes('Review and correct scanned figures')).click()""")
            await browser_helpers.wait_for(
                lambda: cdp.evaluate("!!document.querySelector('iframe[title=\"Original source PDF\"]')"), "original PDF preview")
            await cdp.evaluate("""(() => {
              window.__setInput(document.querySelector('[aria-label="Column heading 1"]'),'Category');
              window.__setInput(document.querySelector('[aria-label="Column heading 2"]'),'Revenue');
            })()""")
            await cdp.evaluate("""(() => {
              window.__setInput(document.querySelector('[aria-label="Category row 1"]'),'Retail');
              window.__setInput(document.querySelector('[aria-label="Revenue row 1"]'),'125');
              Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Add row')).click();
            })()""")
            await browser_helpers.wait_for(
                lambda: cdp.evaluate("!!document.querySelector('[aria-label=\"Category row 2\"]')"), "second review row")
            await cdp.evaluate("""(() => {
              window.__setInput(document.querySelector('[aria-label="Category row 2"]'),'Online');
              window.__setInput(document.querySelector('[aria-label="Revenue row 2"]'),'75');
            })()""")
            assert await cdp.evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('Analyze confirmed rows only')).disabled")
            await cdp.evaluate("""(() => {
              document.querySelector('[aria-label="Verified every cell in row 1"]').click();
              document.querySelector('[aria-label="Verified every cell in row 2"]').click();
              Array.from(document.querySelectorAll('label')).find(l=>l.textContent.includes('I verified the headings')).querySelector('input').click();
            })()""")
            await browser_helpers.wait_for(lambda: cdp.evaluate("!Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('Analyze confirmed rows only')).disabled"), "confirmed review")
            # Editing a previously checked figure must invalidate confirmation.
            await cdp.evaluate("window.__setInput(document.querySelector('[aria-label=\"Revenue row 1\"]'),'126')")
            await browser_helpers.wait_for(lambda: cdp.evaluate("!document.querySelector('[aria-label=\"Verified every cell in row 1\"]').checked"), "edit invalidates row")
            assert await cdp.evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('Analyze confirmed rows only')).disabled")
            await cdp.evaluate("window.__setInput(document.querySelector('[aria-label=\"Revenue row 1\"]'),'125')")
            await cdp.evaluate("""(() => {
              document.querySelector('[aria-label="Verified every cell in row 1"]').click();
              Array.from(document.querySelectorAll('label')).find(l=>l.textContent.includes('I verified the headings')).querySelector('input').click();
            })()""")
            await screenshot("analyst-review-en.jpg")
            await cdp.evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('Analyze confirmed rows only')).click()")
            await browser_helpers.wait_for(lambda: cdp.evaluate("window.__requests.length === 2"), "reviewed-row request")
            submitted = await cdp.evaluate("window.__requests[1]")
            assert submitted["authenticated"] and submitted["cloud"] == "false"
            assert json.loads(submitted["reviewed"]) == review
            await cdp.evaluate("window.__releaseAnalysis()")
            await browser_helpers.wait_for(lambda: text_contains("200.00"), "reviewed calculation")
            # Arabic/RTL and mobile layout use the same real components.
            await cdp.evaluate("document.querySelector('button[title=\"Switch to Arabic\"]').click()")
            await browser_helpers.wait_for(lambda: cdp.evaluate("document.documentElement.dir === 'rtl'"), "Arabic direction")
            await screenshot("analyst-ar.jpg")
            await cdp.send("Emulation.setDeviceMetricsOverride", {
                "width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True,
            })
            await asyncio.sleep(0.3)
            assert await cdp.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), "Mobile layout overflows horizontally"
            await screenshot("analyst-mobile-ar.jpg")
            await cdp.evaluate("document.querySelector('button[aria-label=\"التبديل إلى الوضع الفاتح\"]').click()")
            await browser_helpers.wait_for(lambda: cdp.evaluate("!document.documentElement.classList.contains('dark')"), "light theme")
            await screenshot("analyst-mobile-ar-light.jpg")
            print("PASS: THRIVE logos, live stream/auth, no worker-local polling, source preview, row corrections/confirmation, reviewed calculation, AR/RTL and mobile layout.")
        finally:
            if cdp:
                await cdp.close()
            browser.terminate()
            await browser.wait()


if __name__ == "__main__":
    asyncio.run(main())
