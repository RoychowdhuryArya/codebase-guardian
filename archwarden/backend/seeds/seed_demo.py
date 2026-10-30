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


def seed(store: GraphStore, scale: int = 6) -> None:
    if scale >= 50:
        if isinstance(store, MemoryGraphStore):
            print("[Seed] Seeding enterprise 50-microservice topology into MemoryGraphStore...")
            _seed_memory_50(store)
            print(f"[Seed] 50-service graph created: {store.node_count()} nodes, {store.edge_count()} edges")
        else:
            print("[Seed] Seeding enterprise 50-microservice topology into FalkorDB...")
            _seed_falkor_50(store)
        return

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


# ══════════════════════════════════════════════════════════════════════════════
# Enterprise Scale Topology (50 Microservices across 6 domains)
# ══════════════════════════════════════════════════════════════════════════════

ENTERPRISE_50_SERVICES = [
    # Domain 1: Identity & Security (7)
    {"name": "api-gateway", "domain": "core", "language": "python", "path": "services/api-gateway"},
    {"name": "auth-service", "domain": "auth", "language": "python", "path": "services/auth-service"},
    {"name": "user-profile", "domain": "auth", "language": "typescript", "path": "services/user-profile"},
    {"name": "rbac-service", "domain": "auth", "language": "python", "path": "services/rbac-service"},
    {"name": "session-manager", "domain": "auth", "language": "typescript", "path": "services/session-manager"},
    {"name": "token-vault", "domain": "auth", "language": "python", "path": "services/token-vault"},
    {"name": "mfa-verifier", "domain": "auth", "language": "python", "path": "services/mfa-verifier"},

    # Domain 2: Commerce, Checkout & Orders (9)
    {"name": "order-service", "domain": "orders", "language": "python", "path": "services/order-service"},
    {"name": "cart-service", "domain": "orders", "language": "typescript", "path": "services/cart-service"},
    {"name": "checkout-service", "domain": "orders", "language": "python", "path": "services/checkout-service"},
    {"name": "pricing-engine", "domain": "orders", "language": "python", "path": "services/pricing-engine"},
    {"name": "discounts-service", "domain": "orders", "language": "python", "path": "services/discounts-service"},
    {"name": "tax-calculator", "domain": "orders", "language": "python", "path": "services/tax-calculator"},
    {"name": "coupon-service", "domain": "orders", "language": "typescript", "path": "services/coupon-service"},
    {"name": "giftcard-engine", "domain": "orders", "language": "python", "path": "services/giftcard-engine"},
    {"name": "currency-service", "domain": "orders", "language": "python", "path": "services/currency-service"},

    # Domain 3: Payments, Ledger & Billing (8)
    {"name": "payment-service", "domain": "payments", "language": "python", "path": "services/payment-service"},
    {"name": "payment-gateway", "domain": "payments", "language": "python", "path": "services/payment-gateway"},
    {"name": "ledger-service", "domain": "payments", "language": "python", "path": "services/ledger-service"},
    {"name": "fraud-detector", "domain": "payments", "language": "python", "path": "services/fraud-detector"},
    {"name": "invoicing-service", "domain": "payments", "language": "python", "path": "services/invoicing-service"},
    {"name": "subscription-billing", "domain": "payments", "language": "typescript", "path": "services/subscription-billing"},
    {"name": "payout-relay", "domain": "payments", "language": "python", "path": "services/payout-relay"},
    {"name": "refund-manager", "domain": "payments", "language": "python", "path": "services/refund-manager"},

    # Domain 4: Inventory, Logistics & Fulfillment (9)
    {"name": "inventory-service", "domain": "inventory", "language": "python", "path": "services/inventory-service"},
    {"name": "warehouse-mgmt", "domain": "inventory", "language": "python", "path": "services/warehouse-mgmt"},
    {"name": "shipping-service", "domain": "inventory", "language": "python", "path": "services/shipping-service"},
    {"name": "fleet-tracker", "domain": "inventory", "language": "typescript", "path": "services/fleet-tracker"},
    {"name": "returns-service", "domain": "inventory", "language": "python", "path": "services/returns-service"},
    {"name": "supplier-portal", "domain": "inventory", "language": "typescript", "path": "services/supplier-portal"},
    {"name": "packing-dispatcher", "domain": "inventory", "language": "python", "path": "services/packing-dispatcher"},
    {"name": "barcode-scanner", "domain": "inventory", "language": "python", "path": "services/barcode-scanner"},
    {"name": "procurement-service", "domain": "inventory", "language": "python", "path": "services/procurement-service"},

    # Domain 5: Catalog, Search & Recommendations (8)
    {"name": "catalog-service", "domain": "catalog", "language": "python", "path": "services/catalog-service"},
    {"name": "search-indexer", "domain": "catalog", "language": "python", "path": "services/search-indexer"},
    {"name": "recommendation-engine", "domain": "catalog", "language": "python", "path": "services/recommendation-engine"},
    {"name": "reviews-ratings", "domain": "catalog", "language": "typescript", "path": "services/reviews-ratings"},
    {"name": "category-manager", "domain": "catalog", "language": "python", "path": "services/category-manager"},
    {"name": "media-assets", "domain": "catalog", "language": "typescript", "path": "services/media-assets"},
    {"name": "inventory-lookup", "domain": "catalog", "language": "python", "path": "services/inventory-lookup"},
    {"name": "price-crawler", "domain": "catalog", "language": "python", "path": "services/price-crawler"},

    # Domain 6: Notifications, Observability & Infrastructure (9)
    {"name": "notification-service", "domain": "infra", "language": "python", "path": "services/notification-service"},
    {"name": "email-worker", "domain": "infra", "language": "typescript", "path": "services/email-worker"},
    {"name": "sms-relay", "domain": "infra", "language": "python", "path": "services/sms-relay"},
    {"name": "push-notifier", "domain": "infra", "language": "typescript", "path": "services/push-notifier"},
    {"name": "audit-logger", "domain": "infra", "language": "python", "path": "services/audit-logger"},
    {"name": "metrics-aggregator", "domain": "infra", "language": "python", "path": "services/metrics-aggregator"},
    {"name": "tracing-collector", "domain": "infra", "language": "python", "path": "services/tracing-collector"},
    {"name": "alert-router", "domain": "infra", "language": "python", "path": "services/alert-router"},
    {"name": "event-streamer", "domain": "infra", "language": "python", "path": "services/event-streamer"},
]

ENTERPRISE_CALLS = [
    # Gateway to Domain Routers
    ("api-gateway", "auth-service"),
    ("api-gateway", "order-service"),
    ("api-gateway", "cart-service"),
    ("api-gateway", "catalog-service"),
    ("api-gateway", "user-profile"),
    ("api-gateway", "subscription-billing"),
    # Auth Cluster
    ("auth-service", "user-profile"),
    ("auth-service", "rbac-service"),
    ("auth-service", "session-manager"),
    ("auth-service", "token-vault"),
    ("auth-service", "mfa-verifier"),
    # Commerce & Orders Cluster
    ("order-service", "checkout-service"),
    ("order-service", "pricing-engine"),
    ("order-service", "payment-service"),
    ("order-service", "inventory-service"),
    ("order-service", "notification-service"),
    ("cart-service", "catalog-service"),
    ("cart-service", "pricing-engine"),
    ("cart-service", "discounts-service"),
    ("cart-service", "coupon-service"),
    ("checkout-service", "pricing-engine"),
    ("checkout-service", "tax-calculator"),
    ("checkout-service", "payment-gateway"),
    ("checkout-service", "giftcard-engine"),
    ("pricing-engine", "discounts-service"),
    ("pricing-engine", "currency-service"),
    ("pricing-engine", "tax-calculator"),
    # Payments Cluster
    ("payment-gateway", "fraud-detector"),
    ("payment-gateway", "payment-service"),
    ("payment-gateway", "ledger-service"),
    ("payment-gateway", "invoicing-service"),
    ("payment-gateway", "currency-service"),
    ("payment-gateway", "payout-relay"),
    ("payment-service", "ledger-service"),
    ("payment-service", "fraud-detector"),
    ("payment-service", "refund-manager"),
    ("payment-service", "notification-service"),
    ("subscription-billing", "payment-gateway"),
    ("subscription-billing", "invoicing-service"),
    ("subscription-billing", "user-profile"),
    # Inventory & Fulfillment Cluster
    ("inventory-service", "warehouse-mgmt"),
    ("inventory-service", "shipping-service"),
    ("inventory-service", "procurement-service"),
    ("warehouse-mgmt", "packing-dispatcher"),
    ("warehouse-mgmt", "barcode-scanner"),
    ("warehouse-mgmt", "shipping-service"),
    ("shipping-service", "fleet-tracker"),
    ("shipping-service", "returns-service"),
    ("shipping-service", "notification-service"),
    ("supplier-portal", "inventory-service"),
    ("supplier-portal", "procurement-service"),
    # Catalog & Recommendations
    ("catalog-service", "category-manager"),
    ("catalog-service", "media-assets"),
    ("catalog-service", "inventory-lookup"),
    ("catalog-service", "price-crawler"),
    ("search-indexer", "catalog-service"),
    ("search-indexer", "reviews-ratings"),
    ("recommendation-engine", "catalog-service"),
    ("recommendation-engine", "user-profile"),
    ("recommendation-engine", "reviews-ratings"),
    # Notifications & Observability
    ("notification-service", "email-worker"),
    ("notification-service", "sms-relay"),
    ("notification-service", "push-notifier"),
    ("audit-logger", "event-streamer"),
    ("alert-router", "notification-service"),
    ("alert-router", "email-worker"),
    ("metrics-aggregator", "tracing-collector"),
    ("metrics-aggregator", "alert-router"),
]


def _seed_memory_50(store: MemoryGraphStore) -> None:
    """Populate 50 enterprise services into in-memory NetworkX store."""
    for svc in ENTERPRISE_50_SERVICES:
        store.add_node("Service", {
            "name": svc["name"],
            "kind": "service",
            "domain": svc["domain"],
            "language": svc["language"],
            "path": svc["path"],
        })

    # Tables with ownership
    tables = [
        ("orders", "order-service"),
        ("payments", "payment-service"),
        ("inventory", "inventory-service"),
        ("shipments", "shipping-service"),
        ("users", "user-profile"),
        ("ledgers", "ledger-service"),
        ("catalog", "catalog-service"),
        ("outbox", "order-service"),
        ("warehouse_stock", "warehouse-mgmt"),
    ]
    for table_name, owner in tables:
        store.add_node("Table", {"name": table_name})
        store.add_edge(owner, table_name, "OWNS_TABLE")

    # Topics
    topics = [
        "order.created", "payment.processed", "shipment.dispatched",
        "inventory.depleted", "user.registered", "invoice.issued"
    ]
    for topic_name in topics:
        store.add_node("Topic", {"name": topic_name})

    # Core symbols
    symbols = [
        ("order-service::checkout.create_order", "order-service"),
        ("order-service::db.read_payments_table", "order-service"),
        ("payment-gateway::charge.process_transaction", "payment-gateway"),
        ("payment-service::processor.charge", "payment-service"),
        ("inventory-service::stock.reserve", "inventory-service"),
        ("shipping-service::dispatch.create_shipment", "shipping-service"),
    ]
    for qname, service in symbols:
        store.add_node("Symbol", {"qname": qname, "service": service})

    # Architecture Violations seeded into the 50-service topology:
    # 1. P-001: order-service accesses payment-service's payments table
    store.add_edge(
        "order-service::db.read_payments_table",
        "payments",
        "ACCESSES",
        {"mode": "read", "evidence": "order-service/checkout.py:45"}
    )
    # 2. P-004: dual-write without outbox
    store.add_edge(
        "order-service::checkout.create_order",
        "orders",
        "ACCESSES",
        {"mode": "write", "evidence": "order-service/checkout.py:28"}
    )
    store.add_edge(
        "order-service::checkout.create_order",
        "order.created",
        "PRODUCES",
    )
    # 3. P-005: calls without timeout
    store.add_node("ClientCall", {
        "name": "payment-gateway:/process",
        "service": "checkout-service",
        "target_hint": "payment-gateway",
        "path": "/process",
        "method": "POST",
        "file": "checkout-service/main.py",
        "line": 15,
        "has_timeout": False,
    })
    store.add_edge("order-service::checkout.create_order", "payment-gateway:/process", "MAKES_CALL")
    store.add_edge("payment-gateway:/process", "payment-gateway", "RESOLVES_TO")

    # Inter-service calls
    for source, target in ENTERPRISE_CALLS:
        store.add_edge(source, target, "CALLS", {"via": "http", "count": 1})


def _seed_falkor_50(store: GraphStore) -> None:
    """Populate 50 enterprise services into FalkorDB via Cypher."""
    for svc in ENTERPRISE_50_SERVICES:
        store.query(
            "MERGE (s:Service {name: $name}) SET s.kind='service', s.domain=$domain, s.language=$language, s.path=$path",
            svc
        )

    tables = [
        ("orders", "order-service"),
        ("payments", "payment-service"),
        ("inventory", "inventory-service"),
        ("shipments", "shipping-service"),
        ("users", "user-profile"),
        ("ledgers", "ledger-service"),
        ("catalog", "catalog-service"),
        ("outbox", "order-service"),
        ("warehouse_stock", "warehouse-mgmt"),
    ]
    for tname, owner in tables:
        store.query("MERGE (t:Table {name: $name})", {"name": tname})
        store.query(
            "MATCH (s:Service {name: $owner}), (t:Table {name: $tname}) MERGE (s)-[:OWNS_TABLE]->(t)",
            {"owner": owner, "tname": tname}
        )

    for topic_name in ("order.created", "payment.processed", "shipment.dispatched", "inventory.depleted", "user.registered"):
        store.query("MERGE (top:Topic {name: $name})", {"name": topic_name})

    for source, target in ENTERPRISE_CALLS:
        _create_calls(store, source, target, "http")

    print(f"[Seed] Successfully seeded {len(ENTERPRISE_50_SERVICES)} services and {len(ENTERPRISE_CALLS)} dependency edges.")

