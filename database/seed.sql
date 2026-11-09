-- Fictional products and a fictional customer, no payment data. Seed never
-- replenishes existing inventory or overwrites live prices on subsequent runs.
INSERT INTO products (id, name, description, price) VALUES
('11111111-1111-4111-8111-111111111111', 'Circuit Mini Speaker', 'Portable wireless speaker with a rechargeable battery.', 29.99),
('22222222-2222-4222-8222-222222222222', 'Everyday USB-C Charger', 'Compact 30W charger for phones and small devices.', 19.99),
('33333333-3333-4333-8333-333333333333', 'Recharge AA Battery Kit', 'Four rechargeable AA batteries with a compact charger.', 24.50),
('44444444-4444-4444-8444-444444444444', 'Explorer Electronics Kit', 'Starter components for safe low-voltage hobby projects.', 39.00),
('55555555-5555-4555-8555-555555555555', 'Everyday Phone Stand', 'Adjustable aluminum phone stand for your desk.', 14.00),
('66666666-6666-4666-8666-666666666666', 'Precision Hobby Toolkit', 'Compact screwdriver set for electronics and hobby repair.', 32.00)
ON CONFLICT (id) DO NOTHING;

INSERT INTO inventory (product_id, quantity)
SELECT id, 50 FROM products ON CONFLICT (product_id) DO NOTHING;

INSERT INTO customers (id) VALUES ('fictional-demo-customer') ON CONFLICT (id) DO NOTHING;
