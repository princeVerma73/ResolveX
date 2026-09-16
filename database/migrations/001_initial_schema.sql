-- =============================================================================
-- Migration: 001_initial_schema.sql
-- Description: Core Relational Database Schema for ResolveX Support Platform
-- Step: Step 3 — Database Schema & Migrations
-- Author: ResolveX Engineering
-- =============================================================================

-- Enable extension for UUID generation if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- 1. Helper Function: Auto-update updated_at timestamp
-- =============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- 2. Table: customers
-- Description: Core customer profiles, contact information, and membership tiers.
-- =============================================================================
CREATE TABLE IF NOT EXISTS customers (
    customer_id VARCHAR(64) PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    phone VARCHAR(50),
    tier VARCHAR(20) NOT NULL DEFAULT 'STANDARD' CHECK (tier IN ('STANDARD', 'GOLD', 'PLATINUM')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 3. Table: orders
-- Description: Customer purchase orders, shipping state, and delivery tracking.
-- =============================================================================
CREATE TABLE IF NOT EXISTS orders (
    order_id VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(64) NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PROCESSING', 'SHIPPED', 'DELIVERED', 'CANCELLED', 'FAILED', 'RETURNED')),
    total_amount NUMERIC(10, 2) NOT NULL DEFAULT 0.00 CHECK (total_amount >= 0),
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    shipping_address TEXT,
    tracking_number VARCHAR(100),
    estimated_delivery TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 4. Table: order_items
-- Description: Individual line items associated with customer purchase orders.
-- =============================================================================
CREATE TABLE IF NOT EXISTS order_items (
    item_id VARCHAR(64) PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_name VARCHAR(255) NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 5. Table: payments
-- Description: Financial transactions, payment status, and gateway references.
-- =============================================================================
CREATE TABLE IF NOT EXISTS payments (
    payment_id VARCHAR(64) PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    amount NUMERIC(10, 2) NOT NULL CHECK (amount >= 0),
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'SUCCESS', 'FAILED', 'REFUNDED')),
    payment_method VARCHAR(50) CHECK (payment_method IN ('CREDIT_CARD', 'DEBIT_CARD', 'PAYPAL', 'UPI', 'BANK_TRANSFER', 'WALLET')),
    transaction_ref VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 6. Table: chat_sessions
-- Description: Active conversation threads, entity context memory, and channels.
-- =============================================================================
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(64) REFERENCES customers(customer_id) ON DELETE SET NULL,
    channel VARCHAR(30) NOT NULL DEFAULT 'WEB_CHAT',
    status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'CLOSED', 'ARCHIVED')),
    context_entities JSONB NOT NULL DEFAULT '{}'::jsonb,
    conversation_history JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 7. Table: messages
-- Description: Individual message turns within chat sessions.
-- =============================================================================
CREATE TABLE IF NOT EXISTS messages (
    message_id VARCHAR(64) PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    sender_type VARCHAR(20) NOT NULL CHECK (sender_type IN ('USER', 'AGENT', 'SYSTEM', 'TOOL')),
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 8. Table: tickets
-- Description: Support tickets for human escalation, agent assignment, and issue tracking.
-- =============================================================================
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(64) REFERENCES customers(customer_id) ON DELETE SET NULL,
    session_id VARCHAR(64) REFERENCES chat_sessions(session_id) ON DELETE SET NULL,
    order_id VARCHAR(64) REFERENCES orders(order_id) ON DELETE SET NULL,
    category VARCHAR(30) NOT NULL DEFAULT 'GENERAL' CHECK (category IN ('ORDER', 'BILLING', 'TECHNICAL', 'POLICY', 'GENERAL', 'REFUND', 'SHIPPING')),
    priority VARCHAR(20) NOT NULL DEFAULT 'MEDIUM' CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')),
    status VARCHAR(30) NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'IN_PROGRESS', 'ESCALATED', 'RESOLVED', 'CLOSED')),
    subject VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    assigned_agent VARCHAR(100),
    resolution_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 9. Performance Indexes
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments(order_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_customer_id ON chat_sessions(customer_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_status ON chat_sessions(status);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_tickets_customer_id ON tickets(customer_id);
CREATE INDEX IF NOT EXISTS idx_tickets_session_id ON tickets(session_id);
CREATE INDEX IF NOT EXISTS idx_tickets_order_id ON tickets(order_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority);

-- =============================================================================
-- 10. Automatic updated_at Triggers
-- =============================================================================
DROP TRIGGER IF EXISTS trg_customers_updated_at ON customers;
CREATE TRIGGER trg_customers_updated_at
    BEFORE UPDATE ON customers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_orders_updated_at ON orders;
CREATE TRIGGER trg_orders_updated_at
    BEFORE UPDATE ON orders
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_payments_updated_at ON payments;
CREATE TRIGGER trg_payments_updated_at
    BEFORE UPDATE ON payments
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_chat_sessions_updated_at ON chat_sessions;
CREATE TRIGGER trg_chat_sessions_updated_at
    BEFORE UPDATE ON chat_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trg_tickets_updated_at ON tickets;
CREATE TRIGGER trg_tickets_updated_at
    BEFORE UPDATE ON tickets
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- 11. Role Privileges & Row Level Security (RLS)
-- =============================================================================

-- Schema and sequence usage for all Supabase API roles
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;
GRANT EXECUTE ON ALL ROUTINES IN SCHEMA public TO anon, authenticated, service_role;

-- Full administrative access for trusted backend service_role
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT ALL ON ALL ROUTINES IN SCHEMA public TO service_role;

-- Scoped DML privileges for public / authenticated client roles:
-- 1) Interactive chat & messaging lifecycle:
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE chat_sessions TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE messages TO anon, authenticated;

-- 2) Support ticket submission:
GRANT SELECT, INSERT ON TABLE tickets TO anon, authenticated;

-- 3) Read-only lookup access on operational tables (mutations strictly handled by backend service):
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

-- -----------------------------------------------------------------------------
-- Idempotent RLS Policies (Safely re-runnable)
-- -----------------------------------------------------------------------------

-- chat_sessions: Public/auth clients can create, read, update, and delete sessions
DROP POLICY IF EXISTS "Allow anon and auth to create chat sessions" ON chat_sessions;
CREATE POLICY "Allow anon and auth to create chat sessions" ON chat_sessions
    FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon and auth to read chat sessions" ON chat_sessions;
CREATE POLICY "Allow anon and auth to read chat sessions" ON chat_sessions
    FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon and auth to update chat sessions" ON chat_sessions;
CREATE POLICY "Allow anon and auth to update chat sessions" ON chat_sessions
    FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon and auth to delete chat sessions" ON chat_sessions;
CREATE POLICY "Allow anon and auth to delete chat sessions" ON chat_sessions
    FOR DELETE TO anon, authenticated USING (true);

-- messages: Public/auth clients can append, read, and delete messages in sessions
DROP POLICY IF EXISTS "Allow anon and auth to insert messages" ON messages;
CREATE POLICY "Allow anon and auth to insert messages" ON messages
    FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon and auth to read messages" ON messages;
CREATE POLICY "Allow anon and auth to read messages" ON messages
    FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon and auth to delete messages" ON messages;
CREATE POLICY "Allow anon and auth to delete messages" ON messages
    FOR DELETE TO anon, authenticated USING (true);

-- tickets: Public/auth clients can submit support tickets and query tickets
DROP POLICY IF EXISTS "Allow anon and auth to create tickets" ON tickets;
CREATE POLICY "Allow anon and auth to create tickets" ON tickets
    FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon and auth to read tickets" ON tickets;
CREATE POLICY "Allow anon and auth to read tickets" ON tickets
    FOR SELECT TO anon, authenticated USING (true);

-- customers, orders, order_items, payments: Read-only access for client lookups
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
