"""Multi-page Playwright QA crawler with reproducible evidence and explicit workflows.

Automatic mode is read-only. Mutating CRUD actions run only when the user supplies
an explicit workflow for a dedicated test environment.
"""
from __future__ import annotations
import re
import time
from collections import deque
from urllib.parse import urlparse, urldefrag, urljoin
from pathlib import Path
from playwright.async_api import async_playwright
from fastapi import HTTPException
from .config import settings
from .security import validate_url

IGNORED_FAILURES = ("ERR_ABORTED", "ERR_BLOCKED_BY_CLIENT", "ERR_BLOCKED_BY_ORB", "ERR_BLOCKED_BY_RESPONSE")
IGNORED_CONSOLE = ("ERR_BLOCKED_BY_CLIENT", "ERR_BLOCKED_BY_ORB", "ERR_ABORTED", "content security policy directive")
DANGEROUS = re.compile(r"delete|remove|purchase|buy\s*now|checkout|pay|submit|sign\s*out|log\s*out|unsubscribe|transfer|send\s+money|place\s+order|confirm\s+booking|publish|invite|create\s+account|reset\s+password", re.I)
SAFE_BUTTON = re.compile(r"^(menu|open menu|toggle menu|show|hide|expand|collapse|next|previous|prev|filter|sort|search|view|details|more|less|close|dismiss|tab(?:\s+.*)?)$", re.I)


def _canonical(url: str) -> str:
    clean, _ = urldefrag(url)
    p = urlparse(clean)
    return clean.rstrip("/") if p.path == "/" and not p.query else clean


def _same_origin(a: str, b: str) -> bool:
    x, y = urlparse(a), urlparse(b)
    return (x.scheme, x.hostname, x.port or (443 if x.scheme == "https" else 80)) == (y.scheme, y.hostname, y.port or (443 if y.scheme == "https" else 80))


async def _settle(page):
    try: await page.wait_for_load_state("domcontentloaded", timeout=7000)
    except Exception: pass
    try: await page.wait_for_load_state("networkidle", timeout=1800)
    except Exception: pass
    await page.wait_for_timeout(250)


async def _capture(page, folder: Path, name: str, artifacts: list, full_page=True):
    path = folder / name
    try:
        await page.screenshot(path=str(path), full_page=full_page, animations="disabled", timeout=10000)
        artifacts.append((path, "image/png"))
        return name
    except Exception:
        return ""


async def scan(url: str, run_id: str, depth: str, workflow: list | None = None):
    cfg = settings(); validate_url(url)
    folder = cfg.artifacts / run_id; folder.mkdir(parents=True, exist_ok=True)
    page_limit = {"quick": 3, "standard": 12, "deep": 30}.get(depth, 12)
    data = {
        "target_url": url, "final_url": url, "title": "", "pages": [], "coverage": {},
        "console_errors": [], "http_errors": [], "failed_requests": [], "broken_links": [],
        "inconclusive_links": [], "button_checks": [], "form_checks": [], "workflow_checks": [],
        "page_error": None, "interaction_screenshots": [],
    }
    artifacts = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900}, ignore_https_errors=False, reduced_motion="reduce")
        page = await context.new_page(); page.set_default_timeout(5000)

        async def guard(route):
            try:
                validate_url(route.request.url)
                await route.continue_()
            except Exception:
                await route.abort("blockedbyclient")
        await page.route("**/*", guard)

        current_page = {"url": url}
        page_errors = {}
        def on_console(message):
            if message.type != "error" or len(data["console_errors"]) >= 60: return
            value = message.text.strip()
            if value and not any(x.lower() in value.lower() for x in IGNORED_CONSOLE):
                data["console_errors"].append({"page_url": current_page["url"], "message": value[:700]})
        def on_response(response):
            if response.status < 400 or len(data["http_errors"]) >= 100: return
            req = response.request
            same = _same_origin(response.url, url)
            data["http_errors"].append({"page_url": current_page["url"], "url": response.url[:700], "status": response.status, "resource_type": req.resource_type, "same_origin": same})
            if req.resource_type == "document" and same and response.status in (404, 410, 500, 502, 503, 504):
                page_errors[current_page["url"]] = f"Document navigation returned HTTP {response.status}"
        def on_request_failed(request):
            if len(data["failed_requests"]) >= 60: return
            failure = request.failure or "request failed"
            if any(code in failure for code in IGNORED_FAILURES): return
            data["failed_requests"].append({"page_url": current_page["url"], "url": request.url[:600], "failure": failure[:250]})
        page.on("console", on_console); page.on("response", on_response); page.on("requestfailed", on_request_failed)

        queue = deque([url]); queued = {_canonical(url)}; visited = set(); page_index = 0
        deadline = time.monotonic() + cfg.max_run_seconds
        try:
            while queue and len(visited) < page_limit:
                if time.monotonic() >= deadline:
                    break
                target = queue.popleft(); key = _canonical(target)
                if key in visited: continue
                try: validate_url(target)
                except Exception as exc:
                    data["inconclusive_links"].append({"href": target[:500], "reason": f"Blocked by URL safety policy: {str(exc)[:120]}"}); continue
                current_page["url"] = target
                try:
                    remaining_ms = max(1000, int((deadline - time.monotonic()) * 1000))
                    response = await page.goto(target, wait_until="domcontentloaded", timeout=min(remaining_ms, 15000))
                    await _settle(page)
                    final = page.url; validate_url(final)
                    if not _same_origin(final, url):
                        data["inconclusive_links"].append({"href": target, "reason": "Navigation redirected outside the starting origin and was not crawled."}); continue
                    key = _canonical(final)
                    if key in visited: continue
                    visited.add(key); current_page["url"] = final
                    status = response.status if response else None
                    title = (await page.title())[:250]
                    page_slug = re.sub(r"[^a-zA-Z0-9]+", "-", urlparse(final).path.strip("/") or "home").strip("-")[:45] or "page"
                    page_no = len(visited)
                    shot_name = await _capture(page, folder, f"page-{page_no:02d}-{page_slug}.png", artifacts, True)
                    viewport_name = await _capture(page, folder, f"page-{page_no:02d}-{page_slug}-viewport.png", artifacts, False)
                    headings = [x.strip()[:180] for x in await page.locator("h1,h2,h3").all_text_contents() if x.strip()][:30]
                    links = await page.locator("a[href]").evaluate_all("els=>els.map(a=>({href:a.href,text:(a.innerText||a.getAttribute('aria-label')||'').trim().slice(0,100)}))")
                    internal = []
                    for link in links:
                        href = _canonical(link["href"])
                        if not href.startswith(("http://", "https://")): continue
                        if _same_origin(href, url) and href not in visited and href not in queued:
                            # Avoid logout/delete/action endpoints and file downloads.
                            if re.search(r"/(logout|signout|delete|remove|checkout|payment)(/|$)", urlparse(href).path, re.I): continue
                            queued.add(href); internal.append(href)
                    forms = await page.locator("form:visible").evaluate_all("els=>els.map((f,i)=>({index:i,method:(f.method||'get').toUpperCase(),action:f.action,fields:[...f.querySelectorAll('input,select,textarea')].filter(x=>!['hidden','submit','button','password'].includes((x.type||'').toLowerCase())).map(x=>({name:x.name||'',type:x.type||x.tagName.toLowerCase(),required:!!x.required,label:(x.labels?.[0]?.innerText||x.getAttribute('aria-label')||x.placeholder||'').trim().slice(0,80)}))}))")
                    data["form_checks"].append({"page_url": final, "forms": forms, "form_count": len(forms)})
                    data["pages"].append({"url": final, "title": title, "http_status": status, "headings": headings, "internal_links_found": len(internal), "screenshot": shot_name, "viewport_screenshot": viewport_name, "forms": len(forms)})
                    if page_no == 1: data["title"] = title; data["final_url"] = final
                    if status in (404, 410, 500, 502, 503, 504) and _same_origin(final, url):
                        data["broken_links"].append({"href": final, "status": status, "page_url": final, "screenshot": shot_name, "reason": f"Internal document returned HTTP {status}"})
                    # Safe interaction smoke test: do not submit forms or trigger destructive actions.
                    if depth != "quick":
                        buttons = await page.locator("button:visible,[role=button]:visible").evaluate_all("els=>els.slice(0,40).map((b,i)=>({i,text:(b.innerText||b.getAttribute('aria-label')||b.title||'').trim().slice(0,80),disabled:!!b.disabled,inForm:!!b.closest('form'),type:(b.getAttribute('type')||'').toLowerCase(),href:b.closest('a')?.href||''}))")
                        tested = 0
                        for item in buttons:
                            label = item["text"] or "Unnamed button"
                            if item["disabled"] or item["inForm"] or item["href"] or item["type"] == "submit" or DANGEROUS.search(label) or not SAFE_BUTTON.fullmatch(label.strip()): continue
                            try:
                                loc = page.locator("button:visible,[role=button]:visible").nth(item["i"])
                                await loc.click(timeout=1200); await page.wait_for_timeout(200)
                                shot = await _capture(page, folder, f"page-{page_no:02d}-button-{tested+1}.png", artifacts, False)
                                data["button_checks"].append({"page_url": final, "label": label, "result": "clicked", "screenshot": shot})
                            except Exception as exc:
                                shot = await _capture(page, folder, f"page-{page_no:02d}-button-failed-{tested+1}.png", artifacts, False)
                                data["button_checks"].append({"page_url": final, "label": label, "result": "interaction_failed", "detail": str(exc).splitlines()[0][:160], "screenshot": shot})
                            tested += 1
                            if tested >= (2 if depth == "standard" else 5): break
                    page_index += 1
                    for href in internal:
                        if len(queued) >= page_limit * 5: break
                        queue.append(href)
                except Exception as exc:
                    data["inconclusive_links"].append({"href": target[:600], "reason": str(exc).splitlines()[0][:200]})
                    if page_index == 0: data["page_error"] = str(exc)[:700]
            # User-authored workflows are explicit, ordered browser actions. They may mutate
            # test data; users must only run them against an authorized staging/test system.
            if workflow:
                current_page["url"] = page.url
                for index, step in enumerate(workflow[:60]):
                    if time.monotonic() >= deadline:
                        data["workflow_checks"].append({"step": index + 1, "action": str(step.get("action", "")), "status": "skipped", "error": "Run time budget exhausted"})
                        break
                    action = str(step.get("action", "")); selector = str(step.get("selector", ""))[:500]; value = str(step.get("value", ""))[:2000]
                    result = {"step": index + 1, "action": action, "selector": selector, "status": "passed"}
                    try:
                        if action == "navigate":
                            dest = urljoin(page.url, value); validate_url(dest)
                            if not _same_origin(dest, url): raise ValueError("Workflow navigation must stay on the starting origin")
                            await page.goto(dest, wait_until="domcontentloaded", timeout=15000); await _settle(page)
                        elif action in ("click", "fill", "select", "check", "uncheck"):
                            if not selector: raise ValueError("A selector is required")
                            loc = page.locator(selector).first
                            if action == "click": await loc.click(timeout=5000)
                            elif action == "fill": await loc.fill(value, timeout=5000)
                            elif action == "select": await loc.select_option(value, timeout=5000)
                            elif action == "check": await loc.check(timeout=5000)
                            else: await loc.uncheck(timeout=5000)
                            await page.wait_for_timeout(250)
                        elif action == "assert_visible":
                            if not await page.locator(selector).first.is_visible(): raise AssertionError("Expected element to be visible")
                        elif action == "assert_hidden":
                            if await page.locator(selector).first.is_visible(): raise AssertionError("Expected element to be hidden")
                        elif action == "assert_text":
                            actual = await page.locator(selector).first.inner_text(timeout=5000)
                            if value not in actual: raise AssertionError(f"Expected text not found: {value}")
                        elif action == "assert_text_absent":
                            actual = await page.locator(selector or "body").inner_text(timeout=5000)
                            if value in actual: raise AssertionError(f"Unexpected text is still present: {value}")
                        elif action == "assert_value":
                            actual = await page.locator(selector).first.input_value(timeout=5000)
                            if actual != value: raise AssertionError(f"Expected input value {value!r}, got {actual!r}")
                        elif action == "assert_count":
                            actual = await page.locator(selector).count()
                            if actual != int(value): raise AssertionError(f"Expected {value} matching element(s), got {actual}")
                        elif action == "assert_url":
                            if value not in page.url: raise AssertionError(f"Current URL does not contain: {value}")
                        elif action == "screenshot": pass
                        else: raise ValueError(f"Unsupported workflow action: {action}")
                        result["url"] = page.url
                    except Exception as exc:
                        result["status"] = "failed"; result["error"] = str(exc).splitlines()[0][:300]; result["url"] = page.url
                    result["screenshot"] = await _capture(page, folder, f"workflow-{index+1:02d}.png", artifacts, False)
                    data["workflow_checks"].append(result)
        finally:
            await context.close(); await browser.close()
    data["coverage"] = {"pages_discovered": len(queued), "pages_visited": len(data["pages"]), "page_limit": page_limit, "crawl_truncated": bool(queue) or (time.monotonic() >= deadline and len(data["pages"]) < len(queued)), "forms_observed": sum(x["form_count"] for x in data["form_checks"]), "workflow_steps": len(data["workflow_checks"])}
    return data, artifacts


def deterministic_report(data):
    findings = []
    def add(severity, category, title, description, evidence, recommendation):
        key = (category, str(evidence)[:500])
        if any((f["category"], f["evidence"][:500]) == key for f in findings): return
        findings.append(dict(severity=severity, category=category, title=title, description=str(description)[:2000], evidence=str(evidence)[:2500], recommendation=recommendation))
    page_shots = {x.get("url"): x.get("screenshot") for x in data.get("pages", []) if x.get("screenshot")}
    for raw_item in data.get("console_errors", []):
        item = ({**raw_item, "screenshot": page_shots.get(raw_item.get("page_url"), "")} if isinstance(raw_item, dict) else {"message": str(raw_item), "screenshot": ""})
        add("medium", "console", "Browser JavaScript console error", item.get("message", str(item)), item,
            "Reproduce this error on the listed page and verify its effect on a user journey before prioritizing it.")
    groups = {}
    for item in data.get("http_errors", []):
        host = urlparse(item.get("url", "")).netloc or "unknown"
        key = (host, item.get("status"), item.get("same_origin"), item.get("resource_type"))
        g = groups.setdefault(key, {"origin": host, "status": item.get("status"), "same_origin": bool(item.get("same_origin")), "resource_type": item.get("resource_type"), "occurrences": 0, "sample_urls": [], "pages": []})
        g["occurrences"] += 1
        g.setdefault("page_urls", [])
        if item.get("page_url") and item["page_url"] not in g["page_urls"]: g["page_urls"].append(item["page_url"])
        if len(g["sample_urls"]) < 3: g["sample_urls"].append(item.get("url", "")[:300])
        if item.get("page_url") not in g["pages"]: g["pages"].append(item.get("page_url"))
    for item in groups.values():
        item["screenshots"] = [page_shots[x] for x in item.get("page_urls", []) if page_shots.get(x)]
        status = item["status"]
        if status in (401,403,429): sev, cat, title = "info", "access", "Authentication or access-restricted resource"
        elif item["same_origin"]: sev, cat, title = ("medium" if status >= 500 else "low"), "http", "Same-origin HTTP error"
        else: sev, cat, title = "info", "third_party", "Third-party HTTP response error"
        add(sev, cat, title, f"HTTP {status} for {item['resource_type']} resource; {item['occurrences']} occurrence(s).", item,
            "Inspect the response and confirm whether it blocks a required user-facing feature. Third-party and access-policy responses are informational.")
    for item in data.get("broken_links", []):
        add("high" if item.get("status",0)>=500 else "medium", "page", "Internal page returned an HTTP error", item.get("reason", f"HTTP {item.get('status')}"), item,
            "Fix the route/server response or update the internal link. Review the attached screenshot of this destination.")
    for raw_item in data.get("failed_requests", []):
        item = {**raw_item, "screenshot": page_shots.get(raw_item.get("page_url"), "")}
        add("low", "network", "Browser request failed", item, item, "Reproduce this request on the listed page and confirm whether it affects a required user-facing resource. Browser cancellations are excluded.")
    for item in data.get("button_checks", []):
        if item.get("result")=="interaction_failed": add("medium", "interaction", "Safe button interaction failed", item.get("detail", "Click failed"), item, "Inspect the element, overlays and event handlers; reproduce the interaction manually.")
    for item in data.get("workflow_checks", []):
        if item.get("status")=="failed": add("high", "workflow", f"Workflow step {item['step']} failed", item.get("error", "Workflow assertion failed"), item, "Correct the workflow or investigate the failing application behavior. Check the attached step screenshot.")
    if data.get("page_error"): add("high", "page", "Initial page navigation failed", data["page_error"], data["page_error"], "Check DNS, TLS, server availability and browser navigation errors.")
    coverage=data.get("coverage",{})
    weights={"critical":35,"high":20,"medium":8,"low":3,"info":0}
    score=max(0,100-sum(weights.get(x["severity"],0) for x in findings))
    if not data.get("pages"):
        score = 0
    elif coverage.get("crawl_truncated"):
        score = min(score, 85)
    summary=f"Multi-page browser scan completed: {coverage.get('pages_visited',0)} page(s) visited; {coverage.get('forms_observed',0)} form(s) observed; {len(findings)} finding(s)."
    if coverage.get("crawl_truncated"): summary += " Crawl reached its configured page limit; coverage is incomplete."
    if data.get("workflow_checks"): summary += f" Explicit workflow: {sum(x['status']=='passed' for x in data['workflow_checks'])}/{len(data['workflow_checks'])} steps passed; {sum(x['status']=='skipped' for x in data['workflow_checks'])} skipped."
    summary += " A clean result only applies to the pages and actions actually tested; it is not a guarantee that the whole site is defect-free."
    return {"findings":findings,"score":score,"summary":summary}
