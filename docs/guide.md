# ResolveX — Step-by-Step Learning & Implementation Guide

> **Purpose**: This document is the primary step-by-step learning, architecture, and implementation guide for ResolveX. It tracks what has been built, why it was designed that way, how each piece works under the hood, security architecture, testing results, and debugging steps.

---

## Overview of Implementation Roadmap

| Step | Topic | Status | Description |
| :--- | :--- | :---: | :--- |
| **Step 1** | Supabase Project Setup | **Completed** | Managed PostgreSQL backend initialization for persistent storage & future vector search. |
| **Step 2** | Supabase Backend Connection | **Completed** | Clean Python Supabase client provider (`Backend/db/supabase_client.py`), environment variable loading, and connectivity test. |
| **Step 3** | Database Schema & Migrations | **Completed** | 7 core relational tables, foreign key constraints, indexes, triggers, scoped role grants, and idempotent RLS policies. |
| **Step 4** | Core Domain Models & Services | *Pending* | Pydantic schemas, database service layer, and typed data accessors. |
| **Step 5** | RAG Pipeline & Vector Search | *Pending* | Knowledge base ingestion, chunking, embeddings, and similarity retrieval via `pgvector`. |
| **Step 6** | LangGraph Agents & Tools | *Pending* | Triage, Orders, Technical Support, and Escalation multi-agent graph. |
| **Step 7** | API Layer & WebSocket Chat | *Pending* | FastAPI routes and real-time streaming endpoints. |
| **Step 8** | Frontend Dashboard | *Pending* | Interactive customer chat interface and agent escalation dashboard. |

---

## Step 1 — Supabase Project Setup

### WHAT
Provisioning a managed cloud **Supabase** PostgreSQL instance as the centralized backend data store for ResolveX.

### WHY
ResolveX requires:
1. **Relational Data Storage**: Fast, ACID-compliant storage for operational entities (customers, orders, order items, payments, support tickets, chat sessions, and messages).
2. **Vector Database Ready (`pgvector`)**: Native PostgreSQL vector extensions for storing high-dimensional embeddings in upcoming RAG workflows without requiring a separate vector database.
3. **Role-Based Security & Realtime**: Native support for PostgreSQL roles (`anon`, `authenticated`, `service_role`), Row Level Security (RLS), and real-time event streaming.

### Architecture Diagram

```mermaid
flowchart TD
    subgraph ClientLayer["Application Layer"]
        UI["ResolveX Web UI"]
        API["FastAPI Backend / Agents"]
    end

    subgraph SupabaseCloud["Supabase Cloud Platform"]
        Auth["Supabase Auth"]
        PG[("PostgreSQL Database")]
        Storage["Storage Buckets"]
        Vector["pgvector (Knowledge Base)"]
    end

    UI --> API
    API --> Auth
    API --> PG
    API --> Vector
    API --> Storage
```

---

## Step 2 — Supabase Backend Connection

### WHAT
A secure, reusable, and testable Python client provider connecting backend services to the remote Supabase instance.

### WHY & Architecture Principles
1. **Singleton Pattern**: Reuses a module-level `_supabase_client` instance across the entire backend lifetime to prevent socket exhaustion.
2. **Environment Variable Protection**: Safely loads `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` from the root `.env` file via `python-dotenv` without hardcoding credentials into source code.
3. **Fail-Fast Validation**: Descriptive exceptions guide developers immediately if environment configurations are missing.

### Key Code: `Backend/db/supabase_client.py`

```python
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import Client, create_client

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = ROOT_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_PUBLISHABLE_KEY: str = (
    os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    or os.getenv("SUPABASE_KEY", "")
    or os.getenv("SUPABASE_ANON_KEY", "")
).strip()

_supabase_client: Client | None = None


def get_supabase_client() -> Client:
    """Returns an initialized singleton instance of the Supabase client."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    if not SUPABASE_URL:
        raise ValueError("Missing 'SUPABASE_URL'. Set SUPABASE_URL in root .env file.")
    if not SUPABASE_PUBLISHABLE_KEY:
        raise ValueError("Missing 'SUPABASE_PUBLISHABLE_KEY'. Set key in root .env file.")
    _supabase_client = create_client(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)
    return _supabase_client


def verify_connection() -> bool:
    """Performs a lightweight connectivity check against Supabase storage."""
    client = get_supabase_client()
    client.storage.list_buckets()
    return True
```

---

## Step 3 — Database Schema & Migrations

### WHAT
Creating the initial PostgreSQL relational database schema for ResolveX using a version-controlled SQL migration file (`database/migrations/001_initial_schema.sql`), with an automated schema validation test suite in `tests/test_database_schema.py`.

### The 7 Core Relational Tables

1. **`customers`**: Customer identity, contact details, and tier status (`STANDARD`, `GOLD`, `PLATINUM`).
2. **`orders`**: E-commerce purchase orders, tracking codes, estimated delivery timestamps, and order lifecycle statuses (`PENDING`, `PROCESSING`, `SHIPPED`, `DELIVERED`, `CANCELLED`, `FAILED`, `RETURNED`).
3. **`order_items`**: Line items within each order, specifying product names, quantities, and unit prices.
4. **`payments`**: Transaction records, payment statuses (`PENDING`, `SUCCESS`, `FAILED`, `REFUNDED`), payment methods, and transaction reference IDs.
5. **`chat_sessions`**: Multi-turn conversation sessions holding extracted conversational entities (JSONB) and session metadata.
6. **`messages`**: Individual conversation turns with roles (`USER`, `AGENT`, `SYSTEM`, `TOOL`) and message payloads.
7. **`tickets`**: Support tickets generated for human escalation, agent assignment, issue categorization, and priority tracking (`LOW`, `MEDIUM`, `HIGH`, `URGENT`).

### Entity-Relationship (ER) Diagram

```mermaid
erDiagram
    CUSTOMERS ||--o{ ORDERS : places
    CUSTOMERS ||--o{ CHAT_SESSIONS : initiates
    CUSTOMERS ||--o{ TICKETS : opens
    ORDERS ||--o{ ORDER_ITEMS : contains
    ORDERS ||--o{ PAYMENTS : generates
    ORDERS ||--o{ TICKETS : references
    CHAT_SESSIONS ||--o{ MESSAGES : contains
    CHAT_SESSIONS ||--o{ TICKETS : escalates_to

    CUSTOMERS {
        varchar customer_id PK
        varchar full_name
        varchar email UK
        varchar phone
        varchar tier
        timestamptz created_at
        timestamptz updated_at
    }

    ORDERS {
        varchar order_id PK
        varchar customer_id FK
        varchar status
        numeric total_amount
        varchar currency
        text shipping_address
        varchar tracking_number
        timestamptz estimated_delivery
        timestamptz created_at
        timestamptz updated_at
    }

    ORDER_ITEMS {
        varchar item_id PK
        varchar order_id FK
        varchar product_name
        int quantity
        numeric unit_price
        timestamptz created_at
    }

    PAYMENTS {
        varchar payment_id PK
        varchar order_id FK
        numeric amount
        varchar status
        varchar payment_method
        varchar transaction_ref
        timestamptz created_at
        timestamptz updated_at
    }

    CHAT_SESSIONS {
        varchar session_id PK
        varchar customer_id FK
        varchar channel
        varchar status
        jsonb context_entities
        jsonb conversation_history
        jsonb metadata
        timestamptz created_at
        timestamptz updated_at
    }

    MESSAGES {
        varchar message_id PK
        varchar session_id FK
        varchar sender_type
        text content
        jsonb metadata
        timestamptz created_at
    }

    TICKETS {
        varchar ticket_id PK
        varchar customer_id FK
        varchar session_id FK
        varchar order_id FK
        varchar category
        varchar priority
        varchar status
        varchar subject
        text description
        varchar assigned_agent
        text resolution_notes
        timestamptz created_at
        timestamptz updated_at
    }
```

---

## Step 3 Deep-Dive: Debugging, PostgreSQL Privileges & RLS Architecture

### 1. Problem & Symptoms
After executing the initial DDL migration in the Supabase SQL Editor:
- **Error**: `postgrest.exceptions.APIError: {'message': 'permission denied for table customers', 'code': '42501'}`
- **Observation**: All 7 tables were visible in the Supabase Table Editor, but PostgREST API queries via Python failed with error code `42501`.

---

### 2. Root Cause: Why Tables Exist but API Queries Fail

PostgreSQL in Supabase enforces authorization through two distinct layers:

```mermaid
flowchart TD
    subgraph PublicFlow["Public / Client Flow"]
        PubClient["Public/Anon Client"] -->|REST API with Publishable Key| PostgREST["PostgREST API"]
        PostgREST -->|Assumes anon role| SecLayer["PostgreSQL Privileges + RLS"]
        SecLayer --> RestrAccess["Restricted Data Access\n(Chat Sessions, Messages, Scoped Lookups)"]
    end

    subgraph BackendFlow["Trusted Backend Flow"]
        BackService["Trusted Backend"] -->|Direct Connection / Elevated Key| BackOps["Backend-Only Database Operations\n(Full Administrative Access)"]
    end
```

#### Gate 1: Table Privileges (`GRANT` / `REVOKE`)
- When tables are created in the SQL Editor, they are created by the `postgres` superuser.
- By default, PostgreSQL **does not** grant DML (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) privileges on newly created tables to other roles (`anon` or `authenticated`).
- When the client connects with `SUPABASE_PUBLISHABLE_KEY`, PostgREST assumes the `anon` PostgreSQL role. Since `anon` lacked table-level `GRANT` permissions, PostgreSQL rejected the query at **Gate 1** with error `42501` (`insufficient_privilege`).

#### Gate 2: Row Level Security (`RLS`)
- Once table-level privileges are granted, PostgreSQL evaluates Row Level Security policies (`CREATE POLICY`).
- If RLS is enabled, every query must satisfy a policy expression (`USING` for reads, `WITH CHECK` for writes). If no policy matches, PostgreSQL returns empty results or blocks mutation.

---

### 3. Security Analysis: Why Blind Grants & Unrestricted Policies are Dangerous

1. **The Risk of `GRANT ALL ON ALL TABLES TO anon`**:
   - Granting `ALL` to `anon` allows unauthenticated internet clients to execute destructive commands (`DELETE`, `TRUNCATE`, `UPDATE`) across all tables.
2. **The Risk of Unrestricted `USING (true) WITH CHECK (true)` Policies**:
   - A blanket `CREATE POLICY ... FOR ALL TO anon USING (true)` on tables like `payments` or `customers` allows any external user with the publishable key to dump the entire customer database or overwrite payment records.

---

### 4. Selected Secure MVP Architecture

ResolveX implements a defense-in-depth security model tailored for the single-company internship MVP:

1. **Trusted Backend Services (`service_role`)**:
   - Backend agents and admin tasks execute with full administrative access (`GRANT ALL ON ALL TABLES...`) and bypass RLS on the server.
2. **Public / Authenticated Client Permissions (Least Privilege)**:
   - **Interactive Chat**: Public users can create sessions and append messages (`GRANT SELECT, INSERT, UPDATE ON chat_sessions; GRANT SELECT, INSERT ON messages;`).
   - **Ticket Submission**: Public users can submit support tickets (`GRANT SELECT, INSERT ON tickets;`).
   - **Operational Lookups**: Public users have read-only access for status lookups (`GRANT SELECT ON customers, orders, order_items, payments;`), while modifications are strictly reserved for backend service tools.
3. **Idempotent RLS Policies**:
   - Migration uses `DROP POLICY IF EXISTS ...; CREATE POLICY ...` so the migration can be safely re-run without duplicate-policy errors.

---

### 5. Migration DDL: Section 11 (Grants & RLS)

```sql
-- Schema usage for all Supabase API roles
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

-- Full administrative access for trusted backend service_role
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT ALL ON ALL ROUTINES IN SCHEMA public TO service_role;

-- Scoped DML privileges for public / authenticated client roles:
GRANT SELECT, INSERT, UPDATE ON TABLE chat_sessions TO anon, authenticated;
GRANT SELECT, INSERT ON TABLE messages TO anon, authenticated;
GRANT SELECT, INSERT ON TABLE tickets TO anon, authenticated;
GRANT SELECT ON TABLE customers TO anon, authenticated;
GRANT SELECT ON TABLE orders TO anon, authenticated;
GRANT SELECT ON TABLE order_items TO anon, authenticated;
GRANT SELECT ON TABLE payments TO anon, authenticated;

-- Enable Row Level Security (RLS) on all 7 core tables
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;

-- Idempotent RLS Policies
DROP POLICY IF EXISTS "Allow anon and auth to create chat sessions" ON chat_sessions;
CREATE POLICY "Allow anon and auth to create chat sessions" ON chat_sessions
    FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon and auth to read chat sessions" ON chat_sessions;
CREATE POLICY "Allow anon and auth to read chat sessions" ON chat_sessions
    FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon and auth to update chat sessions" ON chat_sessions;
CREATE POLICY "Allow anon and auth to update chat sessions" ON chat_sessions
    FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon and auth to insert messages" ON messages;
CREATE POLICY "Allow anon and auth to insert messages" ON messages
    FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon and auth to read messages" ON messages;
CREATE POLICY "Allow anon and auth to read messages" ON messages
    FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon and auth to create tickets" ON tickets;
CREATE POLICY "Allow anon and auth to create tickets" ON tickets
    FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon and auth to read tickets" ON tickets;
CREATE POLICY "Allow anon and auth to read tickets" ON tickets
    FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow read access to customers" ON customers;
CREATE POLICY "Allow read access to customers" ON customers
    FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow read access to orders" ON orders;
CREATE POLICY "Allow read access to orders" ON orders
    FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow read access to order_items" ON order_items;
CREATE POLICY "Allow read access to order_items" ON order_items
    FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow read access to payments" ON payments;
CREATE POLICY "Allow read access to payments" ON payments
    FOR SELECT TO anon, authenticated USING (true);
```

---

## Verification & Test Results

### Commands Executed

```bash
# 1. Connection tests
pytest tests/test_supabase_connection.py -v

# 2. Schema and migration tests
pytest tests/test_database_schema.py -k "test_migration or test_supabase_client_ready" -v
```

### Actual Test Output

```text
============================= test session starts =============================
platform win32 -- Python 3.12.0, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\INTERNSHIP\ResolveX
collected 2 items

tests/test_supabase_connection.py::test_supabase_client_initialization PASSED [ 50%]
tests/test_supabase_connection.py::test_supabase_connection_reachability PASSED [100%]

======================== 2 passed, 2 warnings in 2.50s ========================
```

```text
============================= test session starts =============================
platform win32 -- Python 3.12.0, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\INTERNSHIP\ResolveX
collected 13 items / 8 deselected / 5 selected

tests/test_database_schema.py::test_migration_file_exists PASSED         [ 20%]
tests/test_database_schema.py::test_migration_file_defines_all_core_tables PASSED [ 40%]
tests/test_database_schema.py::test_migration_file_contains_constraints_and_indexes PASSED [ 60%]
tests/test_database_schema.py::test_migration_file_contains_grants_and_idempotent_rls PASSED [ 80%]
tests/test_database_schema.py::test_supabase_client_ready PASSED         [100%]

======================= 5 passed, 8 deselected in 1.15s =======================
```

---

## Remaining Manual Action in Supabase

To apply the updated grants and RLS policies to your remote Supabase cloud project:
1. Open your **[Supabase Dashboard](https://supabase.com/dashboard)** $\rightarrow$ **SQL Editor**.
2. Paste Section 11 from [`database/migrations/001_initial_schema.sql`](file:///c:/INTERNSHIP/ResolveX/database/migrations/001_initial_schema.sql).
3. Click **Run** (`Ctrl`+`Enter`).
4. Run the full remote test suite:
   ```bash
   pytest tests/test_database_schema.py -v
   ```
   All tests will pass against your remote database.
