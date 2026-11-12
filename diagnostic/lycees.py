"""Diagnostic temporaire : ouvre le site construit et journalise ce qui empêche l'affichage des lycées."""
import asyncio, json
from playwright.async_api import async_playwright

async def essai(p, nom, **ctx):
    b = await p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    c = await b.new_context(**ctx)
    pg = await c.new_page()
    msgs = []
    pg.on("console", lambda m: msgs.append(f"{m.type}: {m.text}"[:400]))
    pg.on("pageerror", lambda e: msgs.append(f"PAGEERROR: {e}"[:800]))
    pg.on("requestfailed", lambda r: msgs.append(f"REQFAIL: {r.url} {r.failure}"[:300]))
    pg.on("response", lambda r: msgs.append(f"HTTP {r.status} {r.url} {r.headers.get('content-length')}") if "data/" in r.url else None)
    await pg.goto("http://localhost:8000/index.html")
    await pg.wait_for_timeout(15000)
    print(f"\n===== {nom}")
    print("état :", await pg.evaluate("document.getElementById('etat') && document.getElementById('etat').textContent"))
    print("panneau :", (await pg.inner_text("#panneau")).replace("\n", " | ")[:1500])
    print("localStorage :", await pg.evaluate("JSON.stringify(Object.assign({}, localStorage))"))
    for m in msgs:
        print("  ", m)
    # Recherche d'un lycée : la fiche doit s'ouvrir.
    await pg.fill("#recherche", "Louis Bascan"); await pg.wait_for_timeout(1500)
    print("suggestions :", (await pg.inner_text("#suggestions")).replace("\n", " | ")[:400] if await pg.query_selector("#suggestions") else "?")
    await b.close()

async def main():
    async with async_playwright() as p:
        await essai(p, "ordinateur", viewport={"width": 1280, "height": 800})
        await essai(p, "iPhone", **p.devices["iPhone 13"])

asyncio.run(main())
