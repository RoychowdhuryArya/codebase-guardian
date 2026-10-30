# 🚀 Archwarden Deployment Guide: Railway (Backend) & Vercel (Frontend)

This guide walks you through deploying Archwarden into production:
1. **FastAPI Backend on Railway**
2. **Next.js Frontend on Vercel**

---

## 1. Backend Deployment on Railway

### Option A: Railway GitHub Integration (Recommended)
1. Go to [railway.app](https://railway.app) and click **"New Project"**.
2. Select **"Deploy from GitHub repo"** and choose `RoychowdhuryArya/codebase-guardian`.
3. In the project settings:
   - **Root Directory**: `archwarden/backend` (or leave as root, since `railway.json` is configured).
   - **Builder**: Dockerfile (Railway detects `archwarden/backend/Dockerfile`).
4. Under **Variables** (Environment Variables), set:
   ```env
   # Required for Nemotron AI remediation & principle mining
   NVIDIA_API_KEY=your_nvidia_nim_api_key_here
   NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1

   # Graph Engine configuration
   ARCHWARDEN_GRAPH=falkor

   # Optional FalkorDB / Redis instance:
   # If you add a Redis/FalkorDB service on Railway:
   FALKORDB_HOST=${{FalkorDB.RAILWAY_TCP_PROXY_DOMAIN}}
   FALKORDB_PORT=${{FalkorDB.RAILWAY_TCP_PROXY_PORT}}
   ```
   > **Note**: If `FALKORDB_HOST` is omitted or unreachable, Archwarden automatically activates the in-memory fallback store (`MemoryGraphStore`), ensuring the API remains 100% operational.
5. In **Settings** → **Networking**, click **"Generate Domain"** to get your public API URL:
   `https://archwarden-backend-production.up.railway.app`
6. Test your live deployment:
   ```bash
   curl https://archwarden-backend-production.up.railway.app/health
   ```
   It should return `{"status":"ok", ...}`.

---

## 2. Frontend Deployment on Vercel

1. Go to [vercel.com](https://vercel.com) and click **"Add New Project"**.
2. Select the repository `RoychowdhuryArya/codebase-guardian`.
3. Configure project settings:
   - **Framework Preset**: `Next.js` (auto-detected).
   - **Root Directory**: Click "Edit" and select **`archwarden/frontend`**.
   - **Build Command**: `next build` (default).
   - **Output Directory**: `.next` (default).
4. Under **Environment Variables**, add:
   ```env
   NEXT_PUBLIC_API_URL=https://archwarden-backend-production.up.railway.app
   ```
   *(Replace with your actual Railway backend URL from Step 1, without a trailing slash).*
5. Click **"Deploy"**.
6. Vercel will build and deploy your app in ~45 seconds, providing your live production URL:
   `https://archwarden.vercel.app`

---

## 3. Post-Deployment Verification

1. Open your live Vercel URL in your browser: `https://archwarden.vercel.app`.
2. Check the **Dashboard**:
   - The status dot should display `Connected` (green).
   - LLM status will show `Nemotron Ready` (if `NVIDIA_API_KEY` was configured).
3. Switch to the **PR Review** tab:
   - Select any scenario or the `50-Service Enterprise Blast Radius`.
   - Click **`🛡️ Run Architecture Review`** to verify multi-hop blast radius and push-blocking rule evaluation.
   - Click **`✦ Remediate with Nemotron`** on a violation card to verify automated AI patch generation.
