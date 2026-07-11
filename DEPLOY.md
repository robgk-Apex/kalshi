# Put the live board online (no install, ~5 minutes)

This gets you a public web link — like `https://kalshi-dashboard.onrender.com` —
that you can open on any phone or computer and share with other people. Each
visitor gets their **own** positions and P&L (kept in their browser).

You don't need Python, git, or a terminal. You need a **GitHub account** (the
repo already lives there) and a free **Render** account.

## Steps

1. **Open the deploy link**
   👉 https://render.com/deploy?repo=https://github.com/robgk-Apex/kalshi/tree/claude/new-session-ww2byg

2. **Sign in / sign up for Render** — choose **"Sign in with GitHub"**. It's free;
   no credit card for the free plan.

3. **Approve access to the repo.** GitHub will ask if Render can see
   `robgk-Apex/kalshi`. Approve it (you can limit it to just this one repo).

4. Render reads the repo's blueprint (`render.yaml`) and shows a service named
   **kalshi-dashboard**. Leave the settings as-is and click **Apply** / **Create
   Resources**.

5. **Wait for the build** (~2–4 minutes — it says "Building", then "Live"). The
   first free-plan build is the slow part.

6. When it goes **Live**, Render shows your URL at the top, e.g.
   `https://kalshi-dashboard.onrender.com`. **That's your board — open it, share it.**

## Good to know

- **Free plan sleeps.** After ~15 min of no visitors the app naps; the next
  visit takes ~30–60s to wake, then it's instant again. Fine for sharing; if you
  want it always-on, bump it to Render's cheapest paid instance.
- **It shows real Kalshi market data with no keys.** To also show *your* account
  balance, add two secrets in the Render dashboard → your service → **Environment**:
  `KALSHI_KEY_ID` and `KALSHI_PRIVATE_KEY` (paste the contents of your `.pem`).
  Leave them blank for the public, no-keys board.
- **Updates deploy themselves.** `autoDeploy` is on, so any new commit to the
  branch rebuilds the live site automatically.
- **Want a view-only display** (no Take buttons at all)? In the Dockerfile change
  the last line to `CMD ["python", "scripts/dashboard.py", "--live", "--public"]`.

## Prefer to run it on your own computer instead?

You'd need to install **Python 3** (python.org — on Windows the terminal even
offers to install it from the Microsoft Store) and optionally **git**. Then, in a
terminal:

```bash
# no git? download the repo ZIP from GitHub, unzip, and cd into that folder instead
git clone -b claude/new-session-ww2byg https://github.com/robgk-Apex/kalshi
cd kalshi
pip install -r requirements.txt
python scripts/dashboard.py --demo     # synthetic data, always works
# swap --demo for --live once you can reach Kalshi
```

Then open **http://localhost:8787** on that same computer. This is local-only —
not shareable — which is why the Render deploy above is the better fit for
letting other people use it.
