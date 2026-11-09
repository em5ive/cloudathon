-- Backward-compatible, idempotent initial schema. Application connects as
-- retail_app, never as the owner. UUID values originate in the application.
CREATE TABLE IF NOT EXISTS customers (
    id varchar(128) PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS products (
    id uuid PRIMARY KEY,
    name varchar(120) NOT NULL,
    description varchar(1000) NOT NULL,
    price numeric(12,2) NOT NULL CHECK (price >= 0),
    currency char(3) NOT NULL DEFAULT 'USD' CHECK (currency = 'USD')
);

CREATE TABLE IF NOT EXISTS inventory (
    product_id uuid PRIMARY KEY REFERENCES products(id),
    quantity integer NOT NULL CHECK (quantity >= 0)
);

CREATE TABLE IF NOT EXISTS orders (
    id uuid PRIMARY KEY,
    customer_id varchar(128) NOT NULL REFERENCES customers(id),
    status varchar(32) NOT NULL DEFAULT 'received'
        CHECK (status IN ('received', 'processing', 'shipped', 'delivered', 'cancelled')),
    total numeric(12,2) NOT NULL CHECK (total >= 0),
    currency char(3) NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
    idempotency_key varchar(128) NOT NULL,
    request_hash char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (customer_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS orders_customer_created ON orders(customer_id, created_at DESC);

CREATE TABLE IF NOT EXISTS order_items (
    order_id uuid NOT NULL REFERENCES orders(id),
    product_id uuid NOT NULL REFERENCES products(id),
    product_name varchar(120) NOT NULL,
    quantity integer NOT NULL CHECK (quantity BETWEEN 1 AND 100),
    unit_price numeric(12,2) NOT NULL CHECK (unit_price >= 0),
    PRIMARY KEY (order_id, product_id)
);

CREATE TABLE IF NOT EXISTS support_tickets (
    id uuid PRIMARY KEY,
    customer_id varchar(128) NOT NULL REFERENCES customers(id),
    order_id uuid REFERENCES orders(id),
    message varchar(2000) NOT NULL,
    status varchar(24) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved')),
    priority varchar(12) NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
    idempotency_key varchar(128) NOT NULL,
    request_hash char(64) NOT NULL,
    response_answer varchar(1000) NOT NULL,
    ai_available boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (customer_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS tickets_customer_created ON support_tickets(customer_id, created_at DESC);

-- Immutable receipts cover chat and explicit escalation. No in-progress row or
-- connection is held during inference. The primary key plus a short advisory-
-- locked transaction permits only one winning response/ticket per customer/key.
CREATE TABLE IF NOT EXISTS support_requests (
    customer_id varchar(128) NOT NULL REFERENCES customers(id),
    idempotency_key varchar(128) NOT NULL,
    request_hash char(64) NOT NULL,
    response_json jsonb NOT NULL CHECK (jsonb_typeof(response_json) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (customer_id, idempotency_key)
);
