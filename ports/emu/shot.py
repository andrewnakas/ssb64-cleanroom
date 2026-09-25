"""Dev tool: open a page in headless Edge/Chrome via CDP and save screenshots at given times.

    python ports/emu/shot.py <out dir> --url http://localhost:8070/index.html --secs 10,20 [--query keys=...]
        [--sheet]  also write sheet.png (all shots side by side)

Writes shot_<sec>.png and console.txt (page console + exceptions).
"""
import argparse
import base64
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request

import websocket

BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--url", default="http://localhost:8070/index.html")
    ap.add_argument("--secs", default="10,20")
    ap.add_argument("--query", default="")
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--gpu", action="store_true", help="use the real GPU instead of SwiftShader")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    exe = next(b for b in BROWSERS if os.path.exists(b))
    prof = os.path.join(a.out, "_profile")
    shutil.rmtree(prof, ignore_errors=True)
    port = free_port()
    args = [exe, "--headless=new", f"--user-data-dir={prof}", f"--remote-debugging-port={port}",
            "--no-first-run", "--autoplay-policy=no-user-gesture-required", "--window-size=900,760",
            "--remote-allow-origins=*", "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows"]
    if not a.gpu:
        args += ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]
    p = subprocess.Popen(args + ["about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.1)
        ws = websocket.create_connection(ws_url, timeout=60)
        mid = [0]
        console = []

        def send(method, **params):
            mid[0] += 1
            ws.send(json.dumps({"id": mid[0], "method": method, "params": params}))
            want = mid[0]
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == want:
                    return m.get("result", {})
                note(m)

        def note(m):
            meth = m.get("method")
            if meth == "Runtime.consoleAPICalled":
                console.append(" ".join(str(x.get("value", x.get("description", ""))) for x in m["params"]["args"]))
            elif meth == "Runtime.exceptionThrown":
                d = m["params"]["exceptionDetails"]
                console.append("EXC " + d.get("text", "") + " " + str(d.get("exception", {}).get("description", ""))[:300])

        send("Runtime.enable")
        send("Page.enable")
        url = a.url + (("&" if "?" in a.url else "?") + a.query if a.query else "")
        send("Page.navigate", url=url)
        t0 = time.time()
        shots = []
        for s in sorted(float(x) for x in a.secs.split(",")):
            ws.settimeout(0.2)
            while time.time() - t0 < s:
                try:
                    note(json.loads(ws.recv()))
                except Exception:
                    pass
            ws.settimeout(60)
            r = send("Page.captureScreenshot", format="png")
            fn = os.path.join(a.out, f"shot_{s:g}.png")
            open(fn, "wb").write(base64.b64decode(r["data"]))
            shots.append(fn)
        ws.close()
    finally:
        p.kill()
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    open(os.path.join(a.out, "console.txt"), "w", encoding="utf-8").write("\n".join(console))
    print(f"{len(shots)} shots, {len(console)} console lines -> {a.out}")
    for line in console[-8:]:
        print("  |", line[:160])
    if a.sheet and shots:
        from PIL import Image
        ims = [Image.open(f).convert("RGB") for f in shots]
        W = sum(i.width for i in ims)
        sheet = Image.new("RGB", (W, max(i.height for i in ims)))
        x = 0
        for i in ims:
            sheet.paste(i, (x, 0))
            x += i.width
        sheet.save(os.path.join(a.out, "sheet.png"))


if __name__ == "__main__":
    main()
