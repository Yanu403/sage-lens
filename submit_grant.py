"""MiMo 100T Grant Application — Automated submission with CAPTCHA solving.

Flow:
1. Playwright loads the page, extracts reCAPTCHA sitekey + e-token
2. OhMyCaptcha solves reCAPTCHA Enterprise
3. Submit via HTTP with the solved captcha token
"""

import asyncio
import json
import sys
import time
import httpx
from pathlib import Path

# ── Config ───────────────────────────────────────────────
SUBMIT_URL = "https://100t.xiaomimimo.com/api/v1/grant/submit"
PAGE_URL = "https://100t.xiaomimimo.com"
OHMYCAPTCHA_URL = "http://127.0.0.1:8000"
VERIFY_KEY = "da94cc0908d0418982b27819e159df75"

# Application data
EMAIL = "tamvansekali58@gmail.com"
AGENT_TOOL = "sage-lens-telegram-bot"
MODELS = "mimo-v2.5-pro,gemma-4-26b"
WORK_DESCRIPTION = Path("/root/projects/sage-lens/DESCRIPTION.txt").read_text().strip()
PROOF_URL = "https://github.com/Yanu403/sage-lens"
LANG = "id"


async def step1_extract_sitekey():
    """Use Playwright to load the page and extract reCAPTCHA sitekey + e-token."""
    print("\n🔍 Step 1: Extracting sitekey and e-token via Playwright...")
    
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = await ctx.new_page()
        
        # Intercept network to find sitekey
        sitekey = None
        e_token = None
        
        async def handle_request(request):
            nonlocal sitekey, e_token
            url = request.url
            if "recaptcha" in url.lower() and "k=" in url:
                import re
                match = re.search(r'[?&]k=([^&]+)', url)
                if match:
                    sitekey = match.group(1)
            if "miverify" in url.lower() or "verify" in url.lower():
                print(f"  📡 Verify request: {url[:100]}")
        
        async def handle_response(response):
            nonlocal e_token
            url = response.url
            if "miverify" in url or "verify" in url:
                try:
                    body = await response.text()
                    if "e_token" in body or len(body) > 100:
                        e_token = body[:200]
                        print(f"  📡 Verify response: {body[:200]}")
                except:
                    pass
        
        page.on("request", handle_request)
        page.on("response", handle_response)
        
        await page.goto(PAGE_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)
        
        # Also try to find sitekey from page content
        content = await page.content()
        import re
        sitekey_match = re.search(r'data-sitekey="([^"]+)"', content)
        if sitekey_match and not sitekey:
            sitekey = sitekey_match.group(1)
        
        # Try finding in iframe src
        if not sitekey:
            frames = page.frames
            for frame in frames:
                if "recaptcha" in frame.url:
                    match = re.search(r'k=([^&]+)', frame.url)
                    if match:
                        sitekey = match.group(1)
                        break
        
        # Try finding from network requests via JS
        if not sitekey:
            sitekey = await page.evaluate("""
                () => {
                    const el = document.querySelector('[data-sitekey]');
                    if (el) return el.getAttribute('data-sitekey');
                    const iframe = document.querySelector('iframe[src*="recaptcha"]');
                    if (iframe) {
                        const match = iframe.src.match(/k=([^&]+)/);
                        if (match) return match[1];
                    }
                    return null;
                }
            """)
        
        # Get e-token via Xiaomi verify endpoint
        if not e_token:
            try:
                e_token_resp = await page.evaluate("""
                    async () => {
                        try {
                            const resp = await fetch('/api/v1/grant/captcha/init', {method: 'POST'});
                            return await resp.text();
                        } catch(e) {
                            return 'error: ' + e.message;
                        }
                    }
                """)
                if e_token_resp and 'error' not in e_token_resp:
                    e_token = e_token_resp
            except:
                pass
        
        await browser.close()
        
    print(f"  Sitekey: {sitekey or 'NOT FOUND'}")
    print(f"  E-token: {(e_token or 'NOT FOUND')[:80]}")
    return sitekey, e_token


async def step2_solve_captcha(sitekey: str, page_url: str):
    """Use OhMyCaptcha to solve reCAPTCHA Enterprise v2."""
    print("\n🧩 Step 2: Solving reCAPTCHA via OhMyCaptcha...")
    
    async with httpx.AsyncClient(timeout=180) as client:
        # Create task
        task_payload = {
            "task": {
                "type": "RecaptchaV2EnterpriseTaskProxyless",
                "websiteURL": page_url,
                "websiteKey": sitekey,
                "isInvisible": False,
            }
        }
        
        print(f"  Creating task: RecaptchaV2EnterpriseTaskProxyless")
        resp = await client.post(f"{OHMYCAPTCHA_URL}/createTask", json=task_payload)
        data = resp.json()
        print(f"  Response: {json.dumps(data)[:200]}")
        
        if data.get("errorId", 1) != 0:
            print(f"  ❌ Error: {data.get('errorDescription', 'unknown')}")
            # Try alternative task type
            print("  🔄 Trying NoCaptchaTaskProxyless...")
            task_payload["task"]["type"] = "NoCaptchaTaskProxyless"
            resp = await client.post(f"{OHMYCAPTCHA_URL}/createTask", json=task_payload)
            data = resp.json()
            print(f"  Response: {json.dumps(data)[:200]}")
            
            if data.get("errorId", 1) != 0:
                print(f"  ❌ Error: {data.get('errorDescription', 'unknown')}")
                return None
        
        task_id = data.get("taskId")
        if not task_id:
            print(f"  ❌ No taskId returned")
            return None
        
        print(f"  Task ID: {task_id}")
        print(f"  ⏳ Waiting for solution...")
        
        # Poll for result
        for attempt in range(60):
            await asyncio.sleep(5)
            resp = await client.post(f"{OHMYCAPTCHA_URL}/getTaskResult", json={"taskId": task_id})
            result = resp.json()
            
            status = result.get("status", "unknown")
            if status == "ready":
                token = result.get("solution", {}).get("gRecaptchaResponse", "")
                print(f"  ✅ Solved! Token: {token[:60]}...")
                return token
            elif status == "processing":
                print(f"  ⏳ Still processing... ({(attempt+1)*5}s)")
            else:
                print(f"  ❌ Status: {status} — {result.get('errorDescription', '')}")
                return None
        
        print("  ❌ Timeout (5 minutes)")
        return None


async def step3_submit(captcha_token: str):
    """Submit the application with the solved captcha token."""
    print("\n📤 Step 3: Submitting application...")
    
    payload = {
        "email": EMAIL,
        "agentTool": AGENT_TOOL,
        "models": MODELS,
        "workDescription": WORK_DESCRIPTION,
        "proofUrl": PROOF_URL,
        "lang": LANG,
        "captchaToken": captcha_token,
    }
    
    print(f"  Email: {EMAIL}")
    print(f"  Agent Tool: {AGENT_TOOL}")
    print(f"  Models: {MODELS}")
    print(f"  Proof: {PROOF_URL}")
    
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            SUBMIT_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Origin": PAGE_URL,
                "Referer": PAGE_URL + "/",
            },
        )
        
        data = resp.json()
        print(f"\n  Status: {resp.status_code}")
        print(f"  Response: {json.dumps(data, indent=2)}")
        
        if resp.status_code == 200 and data.get("code") == 0:
            print("\n🎉 APPLICATION SUBMITTED SUCCESSFULLY!")
            return True
        else:
            print(f"\n❌ Submission failed: {data.get('message', 'unknown error')}")
            return False


async def main():
    print("=" * 60)
    print("🔮 MiMo 100T Grant Application — Sage Lens")
    print("=" * 60)
    
    # Step 1: Extract sitekey
    sitekey, e_token = await step1_extract_sitekey()
    if not sitekey:
        print("\n❌ Could not extract sitekey. Trying default...")
        sitekey = "6LfCVLAUAAAAALhK-FJADCDF5A4A3KSgVfJMmAV8"  # common Xiaomi key
    
    # Step 2: Solve captcha
    captcha_token = await step2_solve_captcha(sitekey, PAGE_URL)
    if not captcha_token:
        print("\n❌ CAPTCHA solving failed.")
        return False
    
    # Step 3: Submit
    success = await step3_submit(captcha_token)
    return success


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
