# Archwarden Spec Addendum: FalkorDB-First Graph Layer

This addendum **replaces Sections 6, 7 and 11** of `archwarden-build-spec.md`. Everything else in that spec stays as written.

## Why this change

Two things in the last spec revision weakened FalkorDB's role compared to the original design:

1. **Default store flipped.** The original spec said `ARCHWARDEN_GRAPH=falkor|memory`, with `falkor` as the default whenever it is reachable and `memory` only as the offline fallback. The rewrite accidentally made `memory` the default.
2. **openCypher and LLM-to-Cypher drafting were abstracted away.** The original spec used openCypher for blast radius and rule checks, and had Nemotron Super draft and validate executable Cypher during principle mining.

This addendum restores both and makes FalkorDB a first-class part of the design. In short:

- **Graph branching.** The FalkorDB server can clone a graph (`GRAPH.COPY`), and the Python client exposes it as `Graph.copy(clone)`. Archwarden can keep `archwarden_base`, clone it to a per-PR head graph, and mutate only the changed services instead of rebuilding everything in Python memory.
- **Cypher for structure.** Blast radius, cycle detection and call-depth checks are variable-length path queries that read naturally in openCypher.
- **Nemotron Super drafts Cypher.** Natural-language rules and mined patterns become executable queries, which are validated against the live graph before being saved.

`MemoryGraphStore` (NetworkX) remains the **offline fallback** so tests pass without Docker.

---

## 6. Graph Schema and FalkorDB openCypher Engine

### 6.1 FalkorDB-first architecture (`graph/falkor_store.py`)

- **Primary engine:** FalkorDB, run as the `falkordb/falkordb:latest` Docker image. Port `6379` is the Redis/FalkorDB server and port `3000` is the FalkorDB Browser UI. Access it through the MIT-licensed `falkordb` Python client (`from falkordb import FalkorDB`). The server is SSPLv1: run it as a separate Docker service, do not bundle or redistribute it, and say so in the README.
- **Graph branching lifecycle (base -> head -> shadow):**

  | Graph | Purpose | How it is created |
  |---|---|---|
  | `archwarden_base` | Canonical multi-service graph for the base branch | Full build |
  | `archwarden_head` | State after the PR | Clone of base (`base_graph.copy("archwarden_head")`), then re-extract and replace only the services touched by the PR diff |
  | `archwarden_shadow` | Optional, stretch goal: verify a suggested fix | Clone of head, with a proposed patch applied, then re-run the rules and confirm the violation count drops |

  Use a unique name per PR (for example `archwarden_head_<pr_id>`) and delete graphs after the review. `GRAPH.COPY` returns an error if the destination already exists, so delete it first.
- **Read-only queries:** run all rule checks and blast-radius queries with `graph.ro_query(...)`.
- **Offline fallback (`graph/memory_store.py`):** implements the same `GraphStore` protocol in NetworkX, with a Python fallback evaluator for the core rule kinds (forbid cross-unit access, no cycles, max call depth), so unit tests pass offline without Docker.

### 6.2 Node labels and properties

| Label | Properties |
|---|---|
| `Service` | `name`, `kind` (`service` \| `module`), `repo`, `path`, `language`, `framework` |
| `File` | `path`, `service` |
| `Symbol` | `qname`, `kind` (`class` \| `method` \| `handler` \| `client_call`), `file`, `line`, `service` |
| `Route` | `method`, `path_template`, `protocol` (`http` \| `grpc`), `service`, `file`, `line` |
| `ClientCall` | `target_hint`, `method`, `path`, `file`, `line`, `service`, `resolved` (bool), `resolution_source` (`STATIC` \| `NANO_LINKER` \| `UNRESOLVED`), `has_timeout` (bool) |
| `Topic` | `name`, `broker` |
| `Table` | `name`, `store` |
| `ConfigKey` | `name` |

### 6.3 Directed edges

| Edge | From -> To | Properties / notes |
|---|---|---|
| `CONTAINS` | `Service` -> `File`, `File` -> `Symbol` | |
| `DEFINES` | `Symbol` -> `Route` | |
| `MAKES_CALL` | `Symbol` -> `ClientCall` | |
| `RESOLVES_TO` | `ClientCall` -> `Route` | `confidence` (`FACT` \| `DERIVED` \| `HEURISTIC` \| `NANO_LINKED`), `evidence` (`file:line`) |
| `CALLS` | `Service` -> `Service` | Derived from `RESOLVES_TO`. `via` (`http` \| `grpc` \| `queue`), `count`, `sample_locations` |
| `PRODUCES` / `CONSUMES` | `Symbol` -> `Topic` | |
| `ACCESSES` | `Symbol` -> `Table` | `mode` (`read` \| `write`), `evidence` (`file:line`) |
| `OWNS_TABLE` | `Service` -> `Table` | From migrations/config, or a majority-access heuristic (record which) |
| `READS_CONFIG` | `Symbol` -> `ConfigKey` | |

Every edge keeps its `confidence` and `evidence`. Unresolved calls stay as `ClientCall` nodes with `resolved = false` and are counted in the coverage report, never silently dropped.

### 6.4 Core openCypher queries (run via `graph.ro_query()`)

These are **drafts, not yet executed against FalkorDB**. The agent must run each one against a small hand-built graph and fix syntax or semantics before relying on it (see "Notes for the implementing agent" at the end).

```cypher
// 1. k-hop cross-service blast radius
MATCH (s:Service {name: $svc})-[:CALLS*1..2]-(o:Service)
RETURN DISTINCT o.name AS affected_service
```

```cypher
// 2. P-001: forbid cross-service database table access
MATCH (a:Service)-[:CONTAINS*1..3]->(:Symbol)-[x:ACCESSES]->(t:Table)<-[:OWNS_TABLE]-(b:Service)
WHERE a.name <> b.name
RETURN a.name AS from_service, b.name AS owner_service,
       t.name AS table, x.mode AS mode, x.evidence AS evidence
```

```cypher
// 3. P-002: detect distributed synchronous call cycles
MATCH p=(a:Service)-[:CALLS*2..6]->(a)
RETURN [n IN nodes(p) | n.name] AS cycle_path
LIMIT 25
```

```cypher
// 4. P-003: synchronous call chain deeper than the budget (more than 3 hops)
MATCH p=(a:Service)-[:CALLS*4..8]->(b:Service)
WHERE ALL(r IN relationships(p) WHERE r.via IN ['http', 'grpc'])
RETURN [n IN nodes(p) | n.name] AS deep_chain, length(p) AS depth
LIMIT 25
```

```cypher
// 5. P-004: dual-write trigger (handler writes to a table AND produces to a topic, no outbox)
MATCH (s:Service)-[:CONTAINS*1..2]->(sym:Symbol)-[w:ACCESSES {mode: 'write'}]->(t:Table),
      (sym)-[p:PRODUCES]->(top:Topic)
WHERE NOT (s)-[:CONTAINS*1..2]->(:Symbol)-[:ACCESSES {mode: 'write'}]->(:Table {name: 'outbox'})
RETURN s.name AS service, sym.qname AS handler, t.name AS table,
       top.name AS topic, sym.file AS file, sym.line AS line
```

---

## 7. Principles and Nemotron-to-openCypher Mining (`principles/`)

### 7.1 Rule schema (`principles.yaml`)

```yaml
- id: P-001
  statement: "A service never reads or writes another service's database tables."
  kind: graph            # graph (openCypher + Python fallback) | fuzzy (semantic cascade)
  severity: high
  scope: system
  check:
    language: cypher
    query: |
      MATCH (a:Service)-[:CONTAINS*1..3]->(:Symbol)-[x:ACCESSES]->(t:Table)<-[:OWNS_TABLE]-(b:Service)
      WHERE a.name <> b.name
      RETURN a.name AS from, b.name AS to, t.name AS table, x.evidence AS evidence
  evidence:
    support: 41
    total: 41
    baseline_violations: 0
  status: confirmed      # candidate | confirmed | rejected
  source: mined          # mined | adr | manual
  fix_hint: "Call the owning service's HTTP/gRPC API instead of querying its table directly."
```

### 7.2 Base-vs-head delta semantics

Every openCypher rule is evaluated with `ro_query()` against `archwarden_base` and `archwarden_head`. A violation is emitted **only** if the `(from, to, resource)` tuple is present in `archwarden_head` and absent in `archwarden_base`. Pre-existing violations are never reported on a PR; they are listed only by `archwarden audit`.

### 7.3 Nemotron-to-openCypher principle miner (`principles/miner.py`)

1. **Compute statistical support** across the FalkorDB graph (for example table-ownership isolation, maximum call depth, wrapper usage).
2. **Draft with Nemotron 3 Super.** For patterns with support >= 0.85, or when a user runs `archwarden principles add "<natural language rule>"`, Super drafts both the human-readable rule statement and the executable FalkorDB openCypher query.
3. **Validate against the live graph.** Archwarden runs the drafted query against `archwarden_base` with `g.ro_query(draft_query)`. If it raises a Cypher syntax error, or its results do not match the statistical counterexamples from step 1, the error is fed back to Super for one or two repair attempts before anything is written to `principles.candidates.yaml`.
4. **Human confirms.** A person moves candidates to `principles.yaml` with `status: confirmed` (`archwarden principles review`). Never auto-confirm.

---

## 11. Configuration and Environment Variables

```bash
NEBIUS_API_KEY="..."                              # Required for live Nemotron calls
TAVILY_API_KEY="..."                              # Optional: live SDK/RFC doc grounding
ARCHWARDEN_GRAPH="falkor"                         # "falkor" if reachable on FALKORDB_HOST:PORT, else "memory"
FALKORDB_HOST="localhost"
FALKORDB_PORT="6379"
ARCHWARDEN_NANO="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
ARCHWARDEN_SUPER="nvidia/nemotron-3-super-120b-a12b"
ARCHWARDEN_ULTRA="nvidia/Nemotron-3-Ultra-550b-a55b"
ARCHWARDEN_K_HOPS="2"
ARCHWARDEN_MAX_PROMPT_TOKENS="12000"
ARCHWARDEN_LIVE="1"                               # Enable tests/llm_live
```

The model IDs above are defaults only. As in Section 8 of the main spec, verify them at startup with `client.models.list()` and allow environment overrides.

---

## How FalkorDB and Nemotron fit together

- **FalkorDB** (port `6379`, Browser UI on `3000`) is the primary graph engine whenever Docker is up. The `memory` store is used only for offline CI and tests.
- **openCypher via `ro_query`** does the structural work: k-hop blast radius, cross-database access (P-001), call cycles (P-002), call-chain depth (P-003) and dual-write detection (P-004).
- **`Graph.copy()`** gives each PR its own head graph without rebuilding the base. A shadow graph for verifying a suggested fix is an optional stretch goal.
- **Nemotron Super** drafts and repairs Cypher for new rules; the cascade from the main spec (Nano triage, Super judge, Ultra verify) is unchanged.

---

## Notes for the implementing agent

**Verified (from FalkorDB and falkordb-py documentation):**
- `GRAPH.COPY <src> <dest>` duplicates a graph, including nodes, relationships, properties, indexes and constraints. It errors if the destination exists. The copy reflects the source as of when the command started.
- The Python `Graph` class has `copy(clone: str)`, which returns the new graph, and `ro_query(q, params=None, timeout=None)`, which runs a read-only query.

**Not verified. Check before relying on it:**
- **Copy speed.** The documentation does not say how long `GRAPH.COPY` takes. Measure it on your graph sizes before claiming "milliseconds". Claims that FalkorDB traversals run in single-digit milliseconds are marketing figures; measure them on your own queries and report your numbers.
- **Cypher dialect.** Run every query in 6.4 against a small hand-built graph. In particular check list comprehensions (`[n IN nodes(p) | n.name]`), `ALL(...)` over `relationships(p)`, and negated pattern predicates with variable-length paths.
- **P-004 logic.** As drafted, the `NOT (...)` clause tests whether the *service* writes to an `outbox` table anywhere, not whether the *same handler* does. Decide which is intended and fix the query and its tests.
- **P-003 depth.** `*4..8` flags chains of 4 or more hops, which matches a budget of "more than 3". Keep the depth budget configurable.
- **Shadow-graph verification** needs a way to apply a patch to the graph that this spec does not define. Treat it as a stretch goal after the P0 milestones, and do not claim it in the README or video unless it works.
