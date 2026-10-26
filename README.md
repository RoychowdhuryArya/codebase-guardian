# Codebase Guardian AI (Archwarden) 🛡️

> **Real-time Architectural Governance, Blast Radius Analysis, and Principle Guardrails powered by FalkorDB openCypher and NVIDIA Nemotron NIM.**

An intelligent coding assistant designed to intercept PRs and code changes, trace downstream blast radius across microservices using a dynamic knowledge graph, audit architectural principles (cross-service DB access, cycles, outbox dual-writes), and provide AI-generated remediation patches.

---

## 🚀 Key Features

* **🕸️ Graph-Based Microservice Topology (FalkorDB):** Uses high-performance RedisGraph/openCypher engine to maintain canonical architecture graphs (`archwarden_base`), clone per-PR head graphs (`GRAPH.COPY`), and run graph traversals in milliseconds.
* **💥 Multi-Hop Blast Radius Calculation:** Pinpoints which downstream services, routes, and consumers are impacted when an upstream function or service changes.
* **📐 Automated Architectural Principle Audits:**
  - **P-001:** Forbid direct cross-service database access.
  - **P-002:** Detect synchronous call cycles.
  - **P-003:** Synchronous call depth limiter (max 3 hops).
  - **P-004:** Dual-write detector without transactional outbox pattern.
  - **P-005:** Missing HTTP/gRPC client timeout detector.
* **🧠 NVIDIA Nemotron Principle Miner:** Uses **Nemotron-3-Super** to translate human engineering guidelines into executable openCypher queries, validating them against the live graph before admitting them into the rule set.
* **🖥️ Interactive Dashboard & D3 Graph Visualizer:** Next.js 15 dashboard showing real-time service health, interactive force-directed graph view, live audit violations, and PR diff simulation.

---

## 🛠️ Tech Stack

* **Graph Database:** FalkorDB (`falkordb/falkordb:latest`) with openCypher queries
* **AI & LLM:** NVIDIA NIM (`nvidia/nemotron-super-49b-v1`, `nvidia/nemotron-nano-8b-instruct`, `nvidia/nemotron-4-340b-instruct`)
* **Backend:** Python 3.11, FastAPI, Uvicorn, NetworkX (offline test fallback)
* **Frontend:** Next.js 15 (App Router), TypeScript, D3.js v7, Vanilla CSS design tokens
* **DevOps:** Docker Compose, GitHub Actions / Pre-push Hooks

---

## ⚙️ Getting Started

### Prerequisites
* Docker Desktop installed and running
* NVIDIA NIM API Key ([Get free key at build.nvidia.com](https://build.nvidia.com))

### Quickstart with Docker Compose

1. **Clone the repository:**
   ```bash
   git clone https://github.com/RoychowdhuryArya/codebase-guardian.git
   cd codebase-guardian/archwarden
   ```

2. **Configure Environment:**
   ```bash
   cp .env.example .env
   # Add your NVIDIA_API_KEY in .env
   ```

3. **Start All Services:**
   ```bash
   docker compose up -d
   ```

4. **Access the Interfaces:**
   - 🌐 **Frontend Dashboard:** [http://localhost:3001](http://localhost:3001)
   - ⚡ **Backend API & Swagger Docs:** [http://localhost:8080/docs](http://localhost:8080/docs)
   - 🔍 **FalkorDB Browser UI:** [http://localhost:3000](http://localhost:3000)

---

## 👥 Team Workstreams & Architecture Ownership

| Teammate | Focus Area | Key Deliverables |
|---|---|---|
| **Arya** | **Git Hook, CLI & GitHub Actions CI/CD** | `guardian pre-push` CLI hook, GitHub Action PR bot, webhook listener |
| **Alekhya** | **Advanced AST Ingestion & Breaking Changes** | Multi-language AST (TS/Python), breaking route param detection, OpenAPI parser |
| **Chitrakshi** | **AI Remediation & Shadow-Graph Verification** | Nemotron AI code fix generator, shadow-graph verification (`archwarden_shadow`), UI diff viewer |

---

## 📄 License
MIT License. See [LICENSE](LICENSE) for details.
