# 🎬 Archwarden: 3-Minute YouTube Video Demo Script

> **Video Title**: *Archwarden — Autonomous Microservice Architecture Governance with Knowledge Graphs & NVIDIA Nemotron*  
> **Duration**: 3 Minutes (180 Seconds)  
> **Target Audience**: Software Architects, DevOps Engineers, Engineering Leaders, Hackathon Judges  
> **Resolution**: 1080p / 4K 60fps  
> **Setup Required Before Recording**:
> - Backend running: `http://localhost:8080`
> - Frontend running: `http://localhost:3000`
> - Terminal window open on the side (for CLI pre-push hook demo)

---

## ⏱️ Timeline & Scene Breakdown

```
0:00 ── 0:25 │ Hook & The Problem (Dashboard Overview)
0:25 ── 0:55 │ Living Architecture Graph & 50-Service Enterprise Scaling
0:55 ── 1:40 │ PR Review Studio & Cascading Blast Radius Interceptor
1:40 ── 2:20 │ Self-Healing Remediation (NVIDIA Nemotron & Shadow Graph Verification)
2:20 ── 2:45 │ Natural Language Principle Mining & Git Pre-Push Guardrail
2:45 ── 3:00 │ Summary & Call to Action
```

---

## 🎥 Full Script with Visual & Spoken Directions

---

### [0:00 – 0:25] Scene 1: The Hook & The Problem

**Route / Screen**:  
`http://localhost:3000` *(Dashboard Tab)*

**Visual Actions & Pointing Directions**:
1. **[0:00]** Start with the full screen on the **Archwarden Dashboard**.
2. **[0:05]** Move mouse pointer over the **Live System Health Bar** showing:
   - `Connected` status dot
   - `Graph: archwarden_base`
   - `LLM: Nemotron Ready`
3. **[0:12]** Hover over the **Total Violations** and **Microservices Monitored** stat cards.
4. **[0:18]** Highlight the headline: *"Architecture Guardian — Graph-powered microservice governance"*.

**Spoken Narration (Voiceover)**:
> *"Every modern engineering team starts with clean microservice boundaries. But as teams ship dozens of PRs every week, architectural drift sets in: services make undocumented calls, databases are queried across domain boundaries, and an innocent one-line change cascades into catastrophic downstream outages.*
>
> *This is **Archwarden** — an autonomous architecture governance engine that intercepts pull requests, maps multi-hop blast radius across a living OpenCypher knowledge graph, and automatically synthesizes compliant fixes using NVIDIA Nemotron."*

---

### [0:25 – 0:55] Scene 2: Living Architecture Graph & Enterprise Scale

**Route / Screen**:  
Click **"Graph"** tab in the left sidebar (`http://localhost:3000`, Graph View)

**Visual Actions & Pointing Directions**:
1. **[0:25]** Click on **"◎ Graph"** in the sidebar. Let the initial D3 topology animate into view.
2. **[0:32]** Click and drag a couple of nodes to show the physics simulation.
3. **[0:37]** Move cursor to top right and click the button: **`⚡ Scale 50 Services`**.
4. **[0:41]** Point to the node/edge counter updating to **77+ nodes and 180+ dependency edges** across Identity, Core Banking, Checkout, Billing, Logistics, and Data Analytics.
5. **[0:47]** Click on the `payment-gateway` or `order-service` node to reveal the floating **Inspector card** showing routes, connected database tables, and communication protocols.

**Spoken Narration (Voiceover)**:
> *"Let’s look at the codebase. Rather than static documents that become obsolete, Archwarden continuously parses your ASTs and OpenAPI specs into a queryable graph.*
>
> *With a single click, Archwarden scales to an enterprise topology of 50 microservices. Each node represents a real service, endpoint, or database table, with directional dependencies mapped across HTTP, gRPC, and message brokers.*
>
> *Every service’s contracts and boundaries are verified in real time using high-performance openCypher queries."*

---

### [0:55 – 1:40] Scene 3: PR Review Studio & Cascading Blast Radius

**Route / Screen**:  
Click **"⤳ PR Review"** tab in the left sidebar

**Visual Actions & Pointing Directions**:
1. **[0:55]** Click **"⤳ PR Review"** in the sidebar.
2. **[0:59]** Point to the **Diff Source** tabs at the top:
   - Hover over **`📁 Local Git Workspace`** (showing live uncommitted changes detected in the workspace).
   - Hover over **`🐙 GitHub PR Import`** (showing direct URL import from GitHub pull requests).
3. **[1:08]** Click on the 5th scenario card: **`50-Service Enterprise Blast Radius`** (`payment-gateway`).
4. **[1:13]** Click the glowing button at top right: **`🛡️ Run Architecture Review`**.
5. **[1:18]** As the review finishes, highlight the red verdict banner:  
   **`🛑 PUSH BLOCKED — Architectural Regression Detected`**.
6. **[1:24]** Pan cursor across the **Interactive Blast Radius & Regression Graph** on the right:
   - Point to the **pulsing cyan node**: `payment-gateway` *(Touched)*.
   - Point to the **amber nodes**: the 14 downstream microservices in the multi-hop blast radius.
   - Point to the **pulsing red nodes**: detected contract violations.
7. **[1:33]** Click on a node in the graph to show the **Interactive Node Inspector** detailing the exact risk description.

**Spoken Narration (Voiceover)**:
> *"Here is where Archwarden becomes your architectural guardrail. In the PR Review Studio, developers can audit uncommitted local git changes, import live GitHub PRs, or test changes against our preloaded enterprise scenarios.*
>
> *Here, a developer altered the `/charge` endpoint on `payment-gateway`. Watch what happens when we run an architecture review.*
>
> *Instant verdict: **PUSH BLOCKED**. Archwarden performs multi-hop path traversal and discovers that this change doesn't just affect one service — it endangers 14 downstream microservices across Billing, Order Dispatch, and Notifications.*
>
> *Notice our interactive blast radius graph highlighting the origin service in cyan and tracing the exact cascade of affected callers."*

---

### [1:40 – 2:20] Scene 4: AI Remediation & Shadow Graph Verification

**Route / Screen**:  
Scroll down on the **PR Review** page to the **Detected Violations** section

**Visual Actions & Pointing Directions**:
1. **[1:40]** Scroll down to the violation card: `P-001` or `P-006` *(Breaking API Route Change / Cross-Database Access)*.
2. **[1:46]** Click the button on the card: **`✦ Remediate with Nemotron`**.
3. **[1:51]** Show the loading state: *"Querying NVIDIA Nemotron..."*
4. **[1:56]** When the remediation box opens, point to:
   - The **green badge**: `✓ Shadow Graph Verified (0 Regressions)`
   - The clean unified patch diff synthesized by the model.
   - The clear explanation of how the microservice contract was preserved.
5. **[2:10]** Point to the **Shadow Graph Verification** metric: *"Base violations: 1 → Shadow violations: 0. Cycle count: 0."*

**Spoken Narration (Voiceover)**:
> *"Archwarden doesn't just block broken pull requests — it fixes them.*
>
> *By clicking 'Remediate with Nemotron', Archwarden prompts the NVIDIA Nemotron model with the graph subgraph, the offending code diff, and the architectural rule.*
>
> *Nemotron generates a compliant patch. But here is the critical innovation: Archwarden doesn't blindly trust the LLM. It spins up a **Shadow Graph** in memory, applies the patch, and re-executes all openCypher architectural queries.*
>
> *Only when the shadow graph verifies **zero secondary regressions** and safe boundaries is the fix presented to the developer to merge."*

---

### [2:20 – 2:45] Scene 5: Autonomous Principle Mining & CLI Pre-Push Hook

**Route / Screen**:  
Click **"⊛ Principles"** tab, then toggle to the **Terminal Window**

**Visual Actions & Pointing Directions**:
1. **[2:20]** Click **"⊛ Principles"** in the sidebar.
2. **[2:24]** Point to the input field: *"Mine New Principle with Nemotron Super"*.
3. **[2:28]** Highlight how natural language rules like *"Frontend services must never query payment databases directly"* are compiled into formal Cypher graph constraints.
4. **[2:33]** Switch to the **Terminal Window** showing the command:
   ```bash
   python archwarden/cli/guardian.py pre-push
   ```
5. **[2:38]** Run the command and show the terminal output blocking an illegal commit before it ever reaches GitHub.

**Spoken Narration (Voiceover)**:
> *"Teams can also define new governance rules in plain English. Archwarden’s principle miner translates natural language policies directly into executable openCypher queries.*
>
> *And for developers who prefer the terminal, Archwarden integrates seamlessly into your git workflow via our lightweight CLI hook. Run `guardian pre-push`, and regressions are caught locally in under 200 milliseconds before code ever reaches remote CI."*

---

### [2:45 – 3:00] Scene 6: Outro & Call to Action

**Route / Screen**:  
Switch back to Dashboard (`http://localhost:3000`) or project GitHub repository

**Visual Actions & Pointing Directions**:
1. **[2:45]** Return to the full Dashboard view with glowing cards and clean status.
2. **[2:50]** Display project GitHub repository URL on screen overlay:  
   `github.com/RoychowdhuryArya/codebase-guardian`
3. **[2:55]** Fade out with Archwarden logo / project links.

**Spoken Narration (Voiceover)**:
> *"Archwarden turns microservice architecture from static wiki diagrams into an active, self-healing compiler for your entire distributed system.*
>
> *Autonomous governance, multi-hop blast radius, and verified AI remediation. Check out our repository on GitHub and safeguard your architecture today."*

---

## 📋 Quick Recording Checklist for the Creator

- [ ] **Browser Window**: Set zoom to 100% or 110% on `http://localhost:3000`. Fullscreen or 1920x1080 canvas.
- [ ] **Servers Running**: Confirm FastAPI on `8080` and Next.js on `3000`.
- [ ] **Terminal Ready**: Have a terminal sized side-by-side or ready to `Alt+Tab` with `python archwarden/cli/guardian.py pre-push`.
- [ ] **Microphone**: Test audio levels with clear narration pacing.
- [ ] **Cursor Visibility**: Use smooth cursor motions and highlight key buttons before clicking.
