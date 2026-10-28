"""
Archwarden — Demo Seed Data
Creates a rich 6-service graph with deliberate architecture violations:
  - P-001: order-service directly queries payments DB table
  - P-002: shipping↔inventory call cycle
  - P-003: deep call chain: api-gateway→order→payment→fraud→notification (4 hops)
  - P-004: checkout handler writes to orders table AND produces to events topic (no outbox)
  - P-005: several HTTP calls without timeout

Services:
  api-gateway, order-service, payment-service, inventory-service,
  shipping-service, notification-service
"""
from __future__ import annotations

from graph.store_protocol import GraphStore
from graph.memory_store import MemoryGraphStore


def seed(store: GraphStore) -> None:

    if isinstance(store, MemoryGraphStore):
        print("[Seed] Using native in-memory graph seeder...")
        _seed_memory_graph(store)
        print(
            f"[Seed] Memory graph created: "
            f"{store.node_count()} nodes, {store.edge_count()} edges"
        )
        return

    print("[Seed] Seeding demo graph with 6 services and architecture violations...")

    # ── Services ───────────────────────────────────────────────────────────────
    services = [
        {"name": "api-gateway",           "kind": "service", "language": "python", "path": "services/api-gateway"},
        {"name": "order-service",         "kind": "service", "language": "python", "path": "services/order-service"},
        {"name": "payment-service",       "kind": "service", "language": "python", "path": "services/payment-service"},
        {"name": "inventory-service",     "kind": "service", "language": "python", "path": "services/inventory-service"},
        {"name": "shipping-service",      "kind": "service", "language": "python", "path": "services/shipping-service"},
        {"name": "notification-service",  "kind": "service", "language": "python", "path": "services/notification-service"},
    ]
    for svc in services:
        store.query(
            "MERGE (s:Service {name: $name}) SET s.kind=$kind, s.language=$language, s.path=$path",
            svc,
        )

    # ── Tables (with owners) ───────────────────────────────────────────────────
    tables = [
        ("orders",    "order-service"),
        ("payments",  "payment-service"),
        ("inventory", "inventory-service"),
        ("shipments", "shipping-service"),
        ("outbox",    "order-service"),
    ]
    for tname, owner in tables:
        store.query("MERGE (t:Table {name: $name})", {"name": tname})
        store.query(
            "MATCH (s:Service {name: $owner}), (t:Table {name: $tname}) MERGE (s)-[:OWNS_TABLE]->(t)",
            {"owner": owner, "tname": tname},
        )

    # ── Topics ─────────────────────────────────────────────────────────────────
    for topic in ("order.created", "payment.processed", "shipment.dispatched"):
        store.query("MERGE (top:Topic {name: $name})", {"name": topic})

    # ── Files and Symbols ─────────────────────────────────────────────────────

    # --- api-gateway/main.py ---
    store.query("MERGE (f:File {path:'api-gateway/main.py'}) SET f.service='api-gateway'")
    store.query("MATCH (s:Service {name:'api-gateway'}), (f:File {path:'api-gateway/main.py'}) MERGE (s)-[:CONTAINS]->(f)")
    _create_symbol(store, "api-gateway::routes.forward_order", "handler", "api-gateway/main.py", 12, "api-gateway")

    # --- order-service ---
    store.query("MERGE (f:File {path:'order-service/checkout.py'}) SET f.service='order-service'")
    store.query("MATCH (s:Service {name:'order-service'}), (f:File {path:'order-service/checkout.py'}) MERGE (s)-[:CONTAINS]->(f)")
    _create_symbol(store, "order-service::checkout.create_order", "handler", "order-service/checkout.py", 24, "order-service")
    _create_symbol(store, "order-service::db.read_payments_table", "method", "order-service/checkout.py", 45, "order-service")

    # --- payment-service ---
    store.query("MERGE (f:File {path:'payment-service/processor.py'}) SET f.service='payment-service'")
    store.query("MATCH (s:Service {name:'payment-service'}), (f:File {path:'payment-service/processor.py'}) MERGE (s)-[:CONTAINS]->(f)")
    _create_symbol(store, "payment-service::processor.charge", "handler", "payment-service/processor.py", 18, "payment-service")
    _create_symbol(store, "payment-service::fraud.check_inventory", "method", "payment-service/processor.py", 52, "payment-service")

    # --- inventory-service ---
    store.query("MERGE (f:File {path:'inventory-service/stock.py'}) SET f.service='inventory-service'")
    store.query("MATCH (s:Service {name:'inventory-service'}), (f:File {path:'inventory-service/stock.py'}) MERGE (s)-[:CONTAINS]->(f)")
    _create_symbol(store, "inventory-service::stock.reserve", "handler", "inventory-service/stock.py", 30, "inventory-service")
    _create_symbol(store, "inventory-service::stock.update_shipment", "method", "inventory-service/stock.py", 65, "inventory-service")

    # --- shipping-service ---
    store.query("MERGE (f:File {path:'shipping-service/dispatch.py'}) SET f.service='shipping-service'")
    store.query("MATCH (s:Service {name:'shipping-service'}), (f:File {path:'shipping-service/dispatch.py'}) MERGE (s)-[:CONTAINS]->(f)")
    _create_symbol(store, "shipping-service::dispatch.create_shipment", "handler", "shipping-service/dispatch.py", 20, "shipping-service")
    _create_symbol(store, "shipping-service::dispatch.check_inventory_stock", "method", "shipping-service/dispatch.py", 38, "shipping-service")

    # --- notification-service ---
    store.query("MERGE (f:File {path:'notification-service/notifier.py'}) SET f.service='notification-service'")
    store.query("MATCH (s:Service {name:'notification-service'}), (f:File {path:'notification-service/notifier.py'}) MERGE (s)-[:CONTAINS]->(f)")
    _create_symbol(store, "notification-service::notifier.send_email", "handler", "notification-service/notifier.py", 15, "notification-service")

    # ── Routes ─────────────────────────────────────────────────────────────────
    _create_route(store, "POST", "/orders", "order-service", "order-service/checkout.py", 24, "order-service::checkout.create_order")
    _create_route(store, "POST", "/charge", "payment-service", "payment-service/processor.py", 18, "payment-service::processor.charge")
    _create_route(store, "POST", "/reserve", "inventory-service", "inventory-service/stock.py", 30, "inventory-service::stock.reserve")
    _create_route(store, "POST", "/dispatch", "shipping-service", "shipping-service/dispatch.py", 20, "shipping-service::dispatch.create_shipment")
    _create_route(store, "POST", "/notify", "notification-service", "notification-service/notifier.py", 15, "notification-service::notifier.send_email")

    # ── CALLS edges (Service → Service) ───────────────────────────────────────
    # Normal forward calls
    _create_calls(store, "api-gateway", "order-service", "http")
    _create_calls(store, "order-service", "payment-service", "http")
    _create_calls(store, "payment-service", "inventory-service", "http")  # P-003: 4-hop chain
    _create_calls(store, "inventory-service", "notification-service", "http")  # 4th hop

    # P-002: CYCLE — shipping↔inventory
    _create_calls(store, "shipping-service", "inventory-service", "http")
    _create_calls(store, "inventory-service", "shipping-service", "http")  # Creates cycle!

    # ── VIOLATION: P-001 ──────────────────────────────────────────────────────
    # order-service directly accesses the payments table (owned by payment-service)
    store.query(
        """
        MATCH (sym:Symbol {qname:'order-service::db.read_payments_table'}),
              (t:Table {name:'payments'})
        MERGE (sym)-[x:ACCESSES]->(t)
        SET x.mode='read', x.evidence='order-service/checkout.py:45'
        """
    )

    # ── VIOLATION: P-004 ──────────────────────────────────────────────────────
    # checkout handler writes to orders AND produces to order.created (no outbox)
    store.query(
        """
        MATCH (sym:Symbol {qname:'order-service::checkout.create_order'}),
              (t:Table {name:'orders'})
        MERGE (sym)-[x:ACCESSES]->(t)
        SET x.mode='write', x.evidence='order-service/checkout.py:28'
        """
    )
    store.query(
        """
        MATCH (sym:Symbol {qname:'order-service::checkout.create_order'}),
              (top:Topic {name:'order.created'})
        MERGE (sym)-[:PRODUCES]->(top)
        """
    )

    # ── VIOLATION: P-005 ──────────────────────────────────────────────────────
    # Several HTTP calls without timeout
    cc_data = [
        {"svc": "order-service", "sym": "order-service::checkout.create_order", "target": "payment-service", "path": "/charge", "method": "POST"},
        {"svc": "payment-service", "sym": "payment-service::fraud.check_inventory", "target": "inventory-service", "path": "/reserve", "method": "POST"},
    ]
    for cc in cc_data:
        store.query(
            """
            MERGE (c:ClientCall {target_hint: $target, path: $path, service: $svc})
            SET c.method=$method, c.file=$svc+'/main.py', c.line=1,
                c.resolved=true, c.resolution_source='HEURISTIC', c.has_timeout=false
            WITH c
            MATCH (sym:Symbol {qname: $sym})
            MERGE (sym)-[:MAKES_CALL]->(c)
            WITH c
            MATCH (callee:Service {name: $target})
            MERGE (c)-[:RESOLVES_TO {confidence:'HEURISTIC'}]->(callee)
            """,
            cc,
        )

    # Normal table accesses (owned tables)
    store.query(
        """
        MATCH (sym:Symbol {qname:'order-service::checkout.create_order'}),
              (t:Table {name:'orders'})
        MERGE (sym)-[x:ACCESSES]->(t)
        SET x.mode='write', x.evidence='order-service/checkout.py:28'
        """
    )
    store.query(
        """
        MATCH (sym:Symbol {qname:'payment-service::processor.charge'}),
              (t:Table {name:'payments'})
        MERGE (sym)-[x:ACCESSES]->(t)
        SET x.mode='write', x.evidence='payment-service/processor.py:22'
        """
    )
    store.query(
        """
        MATCH (sym:Symbol {qname:'inventory-service::stock.reserve'}),
              (t:Table {name:'inventory'})
        MERGE (sym)-[x:ACCESSES]->(t)
        SET x.mode='write', x.evidence='inventory-service/stock.py:35'
        """
    )

    print("[Seed] Done — 6 services, 4 violations (P-001, P-002, P-003, P-004, P-005)")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_symbol(store: GraphStore, qname: str, kind: str, file: str, line: int, service: str) -> None:
    store.query(
        """
        MERGE (sym:Symbol {qname: $qname})
        SET sym.kind=$kind, sym.file=$file, sym.line=$line, sym.service=$service
        WITH sym
        MATCH (f:File {path: $file})
        MERGE (f)-[:CONTAINS]->(sym)
        """,
        {"qname": qname, "kind": kind, "file": file, "line": line, "service": service},
    )


def _create_route(store: GraphStore, method: str, path: str, service: str, file: str, line: int, handler_qname: str) -> None:
    store.query(
        """
        MERGE (r:Route {path_template: $path, service: $service})
        SET r.method=$method, r.protocol='http', r.file=$file, r.line=$line
        WITH r
        MATCH (sym:Symbol {qname: $handler_qname})
        MERGE (sym)-[:DEFINES]->(r)
        """,
        {"method": method, "path": path, "service": service, "file": file, "line": line, "handler_qname": handler_qname},
    )


def _create_calls(store: GraphStore, from_svc: str, to_svc: str, via: str) -> None:
    store.query(
        """
        MATCH (a:Service {name: $from_svc}), (b:Service {name: $to_svc})
        MERGE (a)-[c:CALLS]->(b)
        SET c.via=$via, c.count=1
        """,
        {"from_svc": from_svc, "to_svc": to_svc, "via": via},
    )

def _seed_memory_graph(store: MemoryGraphStore) -> None:
    """Populate the offline graph using native NetworkX helpers."""
    services = [
        "api-gateway",
        "order-service",
        "payment-service",
        "inventory-service",
        "shipping-service",
        "notification-service",
    ]

    for name in services:
        store.add_node("Service", {
            "name": name,
            "kind": "service",
            "language": "python",
            "path": f"services/{name}",
        })

    tables = [
        ("orders", "order-service"),
        ("payments", "payment-service"),
        ("inventory", "inventory-service"),
        ("shipments", "shipping-service"),
        ("outbox", "order-service"),
    ]

    for table_name, owner in tables:
        store.add_node("Table", {"name": table_name})
        store.add_edge(owner, table_name, "OWNS_TABLE")

    for topic_name in (
        "order.created",
        "payment.processed",
        "shipment.dispatched",
    ):
        store.add_node("Topic", {"name": topic_name})

    symbols = [
        ("order-service::checkout.create_order", "order-service"),
        ("order-service::db.read_payments_table", "order-service"),
        ("payment-service::processor.charge", "payment-service"),
        ("payment-service::fraud.check_inventory", "payment-service"),
        ("inventory-service::stock.reserve", "inventory-service"),
        ("inventory-service::stock.update_shipment", "inventory-service"),
        ("shipping-service::dispatch.create_shipment", "shipping-service"),
        ("shipping-service::dispatch.check_inventory_stock", "shipping-service"),
    ]

    for qname, service in symbols:
        store.add_node("Symbol", {
            "qname": qname,
            "service": service,
        })

    # P-001: order-service accesses another service's payments table.
    store.add_edge(
        "order-service::db.read_payments_table",
        "payments",
        "ACCESSES",
        {"mode": "read", "evidence": "order-service/checkout.py:45"},
    )

    # P-004: checkout writes to orders and publishes an event.
    store.add_edge(
        "order-service::checkout.create_order",
        "orders",
        "ACCESSES",
        {"mode": "write", "evidence": "order-service/checkout.py:28"},
    )
    store.add_edge(
        "order-service::checkout.create_order",
        "order.created",
        "PRODUCES",
    )

    # P-005: outbound client calls without a timeout.
    for service, target, path in [
        ("order-service", "payment-service", "/charge"),
        ("payment-service", "inventory-service", "/reserve"),
    ]:
        call_id = f"{service}:{path}"
        store.add_node("ClientCall", {
            "name": call_id,
            "service": service,
            "target_hint": target,
            "path": path,
            "method": "POST",
            "file": f"{service}/main.py",
            "line": 1,
            "has_timeout": False,
        })
        caller = (
            "order-service::checkout.create_order"
            if service == "order-service"
            else "payment-service::fraud.check_inventory"
        )
        store.add_edge(caller, call_id, "MAKES_CALL")
        store.add_edge(call_id, target, "RESOLVES_TO")

    # P-002: shipping and inventory call each other.
    # P-003: the gateway-to-notification chain is four hops.
    calls = [
        ("api-gateway", "order-service"),
        ("order-service", "payment-service"),
        ("payment-service", "inventory-service"),
        ("inventory-service", "notification-service"),
        ("shipping-service", "inventory-service"),
        ("inventory-service", "shipping-service"),
    ]

    for source, target in calls:
        store.add_edge(source, target, "CALLS", {"via": "http", "count": 1})
