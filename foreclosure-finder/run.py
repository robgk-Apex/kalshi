"""One-click launcher: installs what's needed, starts the site, opens your browser."""
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(HERE, "rentcast-key.txt")


def fail(msg):
    print("\n" + "=" * 60 + "\nCOULD NOT START: " + msg + "\n" + "=" * 60)
    input("\nPress Enter to close this window...")
    sys.exit(1)


def ensure_packages():
    missing = []
    for mod, pkg in (("fastapi", "fastapi"), ("uvicorn", "uvicorn"), ("httpx", "httpx")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        print("Installing " + ", ".join(missing) + " (one time only)...")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", *missing])
        if r.returncode != 0:
            fail("pip couldn't install " + ", ".join(missing) + ". Check your internet connection.")


def free_port(start=8000):
    for port in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    fail("no free port between 8000 and 8050.")


def open_when_ready(port):
    url = f"http://localhost:{port}"
    for _ in range(120):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.5)
    print(f"\nSite is ready: {url}\nKeep this window open while you search. Close it to stop.\n")
    webbrowser.open(url)


def rentcast_key():
    if os.environ.get("RENTCAST_API_KEY"):
        return
    key = ""
    if os.path.exists(KEY_FILE):
        key = open(KEY_FILE).read().strip()
    if not key:
        key = input("Paste your RentCast API key for sold comps (or press Enter to skip): ").strip()
        if key:
            open(KEY_FILE, "w").write(key)
    if key:
        os.environ["RENTCAST_API_KEY"] = key


def main():
    if sys.version_info < (3, 10):
        fail(f"this needs Python 3.10 or newer; you have {sys.version.split()[0]}. "
             "Install the latest from https://www.python.org/downloads/")
    os.chdir(HERE)
    sys.path.insert(0, HERE)
    ensure_packages()
    rentcast_key()
    port = free_port()
    print(f"Starting Foreclosure Finder on port {port}...")
    threading.Thread(target=open_when_ready, args=(port,), daemon=True).start()
    import uvicorn
    from app.server import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
        fail("see the error above. Send a screenshot of this window to Claude.")
