# GB-Backend (QDIO E-Commerce API)

FastAPI backend for authentication, profiles, products, orders, payments, returns, partners, supplier sync, and Shopify integration.

## Tech Stack
- FastAPI
- Supabase (Auth + Postgres)
- Razorpay (online payments)
- AWS SES (order emails)
- ReportLab (PDF invoice generation)

## Project Structure
- `main.py` - app bootstrap, CORS, router registration
- `routers/` - API endpoints
- `schemas/` - Pydantic request/response models
- `services.py` - DB clients, auth helpers, external integrations
- `utils.py` - pricing/invoice/lucky-number/supplier-shopify utility logic

## Environment Variables
Required values used by the code:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_ANON_KEY`
- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`
- `SUPPLIER_API_URL`
- `SUPPLIER_API_KEY`
- `SYNC_SECRET`
- `AWS_REGION`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `SES_FROM_EMAIL`
- `SHOPIFY_CLIENT_ID`
- `SHOPIFY_CLIENT_SECRET`
- `SHOPIFY_REDIRECT_URL`

## Run Locally
```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

## Base API Notes
- Auth is bearer token based (`OAuth2PasswordBearer`, token URL: `/auth/login`).
- Most protected endpoints depend on `get_current_user` from `services.py`.
- CORS is enabled for `qdio.in`, `qdio.shop`, and localhost dev origins.

## Router Overview
Registered routers in `main.py`:
- `auth_router` -> `/auth/*`
- `profiles_router` -> `/profiles/*`
- `orders_router` -> `/orders/*`
- `partners_router` -> `/partners/*`
- `returns_router` -> `/returns/*`
- `products_router` -> `/products/*`
- `admin_router` -> mixed paths (`/admin/*`, `/payment/*`, `/brands`, etc.)
- `suppliers_router` -> mixed paths (`/sync/supplier/*`, `/suppliers`)
- `shopify_router` -> `/shopify/*`

Note: A root endpoint function (`read_root`) exists in `main.py` but its local router is not included via `app.include_router(router)`, so `/` may not be exposed.

---

## 1) Authentication Router (`routers/auth_routers.py`)
Prefix: `/auth`

### Endpoints
| Method | Path | Auth | Request Model | Response Model | Description |
|---|---|---|---|---|---|
| POST | `/auth/signup` | No | `UserCreate` | `UserResponse` | Creates auth user in Supabase, validates optional `partner_code`, upserts profile. |
| POST | `/auth/login` | No | `OAuth2PasswordRequestForm` | `Token` | Email/password login, returns access + refresh token. |
| GET | `/auth/me` | Yes | - | JSON | Returns current auth user + profile fields. |
| POST | `/auth/forgot-password` | No | `UserForgotPassword` | JSON | Sends Supabase password reset email with fixed redirect URL. |
| POST | `/auth/reset-password` | Yes (token) | `UserResetPassword` | JSON | Updates user password using provided bearer token session. |

### Functions
- `signup(user: UserCreate)`
- `login(form_data: OAuth2PasswordRequestForm)`
- `me(user: UserResponse = Depends(get_current_user))`
- `forgot_password(data: UserForgotPassword)`
- `reset_password(data: UserResetPassword, token: str = Depends(oauth2_scheme))`

---

## 2) Profiles Router (`routers/profiles_routers.py`)
Prefix: `/profiles`

### Endpoints
| Method | Path | Auth | Request Model | Response Model | Description |
|---|---|---|---|---|---|
| GET | `/profiles/me` | Yes | - | `Profile` | Fetches current user profile, auto-creates profile if missing. |
| PUT | `/profiles/me` | Yes | `ProfileBase` | `Profile` | Updates authenticated user profile. |

### Functions
- `get_my_profile(user: UserResponse = Depends(get_current_user))`
- `update_my_profile(profile: ProfileBase, user: UserResponse = Depends(get_current_user))`

---

## 3) Products Router (`routers/products_routers.py`)
Prefix: `/products`

### Endpoints
| Method | Path | Auth | Request Model | Response Model | Description |
|---|---|---|---|---|---|
| GET | `/products/` | No | - | `list[Product]` | Lists products sorted by `created_at desc`; parses `images` JSON string to list. |
| GET | `/products/{product_id}` | No | - | `Product` | Single product by ID with `images` parsing. |
| GET | `/products/base/{base_product_id}` | No | - | `list[Product]` | Active products by base product id. |
| PUT | `/products/{product_id}` | Yes | `ProductUpdate` | `Product` | Partial product update, sets `updated_at`. |
| GET | `/products/{product_id}/variants` | No | - | JSON | Lists variants for product. |
| GET | `/products/variants/{variant_id}` | No | - | JSON | Fetches single variant by variant ID. |

### Functions
- `get_products()`
- `get_product(product_id: int)`
- `get_products_by_base_id(base_product_id: int)`
- `update_product(product_id: int, product_update: ProductUpdate, current_user: UserResponse = Depends(get_current_user))`
- `get_product_variants(product_id: int)`
- `get_variant(variant_id: int)`

---

## 4) Orders Router (`routers/orders_routers.py`)
Prefix: `/orders`

### Endpoints
| Method | Path | Auth | Request Model | Response Model | Description |
|---|---|---|---|---|---|
| POST | `/orders/price-preview` | No | `OrderCreate` | JSON | Validates items and optional coupon, calculates subtotal/discount/gst/shipping/cod/total. |
| POST | `/orders/` | Yes | `OrderCreate` | `Order` | Creates order, validates profile + stock + coupon, inserts order/items, creates Razorpay order for online payments, deducts stock. |
| GET | `/orders/` | No | Query `partner_id?` | JSON | Lists all orders, optional filter by partner. |
| GET | `/orders/me` | Yes | - | `list[Order]` | Lists current user orders with return eligibility flags. |
| GET | `/orders/me/{order_id}` | Yes | - | `Order` | Single user order with return flags per item. |
| PUT | `/orders/{order_id}` | Yes | `OrderUpdate` | `Order` | Updates `opt_out_delivery` only. |
| GET | `/orders/{order_id}/invoice` | Yes | - | PDF | Generates invoice PDF, only when `payment_status` is `Completed`. |
| POST | `/orders/admin/{order_id}/delivery-status` | No explicit auth check | `DeliveryStatusCreate` | JSON | Inserts delivery status log; sets delivery/return window when delivered. |

### Functions
- `price_preview(order: OrderCreate)`
- `create_order(order: OrderCreate, background_tasks: BackgroundTasks, current_user: UserResponse = Depends(get_current_user))`
- `get_orders(partner_id: Optional[str] = Query(None))`
- `get_my_orders(current_user: UserResponse = Depends(get_current_user))`
- `get_my_single_order(order_id: int, current_user: UserResponse = Depends(get_current_user))`
- `update_order(order_id: int, order_update: OrderUpdate, current_user: UserResponse = Depends(get_current_user))`
- `get_order_invoice(order_id: int, current_user: UserResponse = Depends(get_current_user))`
- `update_delivery_status(order_id: int, payload: DeliveryStatusCreate)`

---

## 5) Returns Router (`routers/returns_routers.py`)
Prefix: `/returns`

### Endpoints
| Method | Path | Auth | Request Model | Response Model | Description |
|---|---|---|---|---|---|
| POST | `/returns/returns` | Yes | `ReturnCreate` | JSON | Creates return request after delivery/window/item validation. |
| GET | `/returns/returns` | Yes | Query `order_id` | `list[ReturnResponse]` | Fetches current user returns for an order. |
| PATCH | `/returns/{return_id}` | No explicit auth check | `ReturnUpdate` | `ReturnResponse` | Admin-style return status update. |
| GET | `/returns/admin/returns` | No explicit auth check | Query `status?` | `list[ReturnResponse]` | Lists all returns with optional status filter. |

### Functions
- `to_ist(dt)`
- `create_return(payload: ReturnCreate, current_user: UserResponse = Depends(get_current_user))`
- `get_my_returns(order_id: int, current_user: UserResponse = Depends(get_current_user))`
- `update_return_status(return_id: int, payload: ReturnUpdate)`
- `get_all_returns(status: ReturnStatusEnum | None = None)`

---

## 6) Partners Router (`routers/partners_routers.py`)
Prefix: `/partners`

### Endpoints
| Method | Path | Auth | Request Model | Response Model | Description |
|---|---|---|---|---|---|
| POST | `/partners/activate` | Yes | `PartnerActivateRequest` | JSON | Marks profile as partner for a valid `partner_id`. |
| POST | `/partners/` | No | `PartnerCreate` | `PartnerResponse` | Submits partner application. |
| GET | `/partners/` | No | - | `list[PartnerResponse]` | Lists all partner applications. |
| GET | `/partners/coupons` | Yes | - | JSON | Lists active coupons for current partner account. |
| GET | `/partners/dashboard` | Yes | - | `PartnerDashboardResponse` | Partner metrics: sales, coupons, orders, products sold, brands, earnings. |

### Functions
- `activate_partner(payload: PartnerActivateRequest, user: UserResponse = Depends(get_current_user))`
- `submit_partner_application(payload: PartnerCreate)`
- `get_all_partner_applications()`
- `get_partner_coupons(user: UserResponse = Depends(get_current_user))`
- `get_partner_dashboard(current_user: UserResponse = Depends(get_current_user))`

---

## 7) Admin Router (`routers/admin_routers.py`)
Prefix: none (mixed paths)

### Endpoints
| Method | Path | Auth | Request Model | Response Model | Description |
|---|---|---|---|---|---|
| POST | `/admin/coupons` | No explicit auth check | `AdminCouponCreateRequest` | JSON | Creates coupon with auto-generated code from brand/partner context. |
| POST | `/payment/verify` | Yes | `PaymentVerificationRequest` | JSON | Razorpay signature verification, order status update, coupon usage increment, email dispatch. |
| GET | `/delivery-partners` | Yes | - | `list[DeliveryPartner]` | Lists delivery partners. |
| GET | `/brands` | No | - | `list[BrandResponse]` | Lists all brands. |
| GET | `/categories` | No | Query `segment?` | `list[CategoryResponse]` | Lists categories, optionally filtered by segment. |
| GET | `/coupons` | No | - | JSON | Lists all coupons for admin view. |

### Functions
- `to_ist(dt)`
- `create_coupon_admin(payload: AdminCouponCreateRequest)`
- `verify_payment(data: PaymentVerificationRequest, background_tasks: BackgroundTasks, current_user: UserResponse = Depends(get_current_user))`
- `get_delivery_partners(current_user: UserResponse = Depends(get_current_user))`
- `get_brands()`
- `get_categories(segment: Optional[str] = Query(default=None))`
- `get_all_coupons()`

---

## 8) Suppliers Router (`routers/suppliers_routers.py`)
Prefix: none (mixed paths)

### Endpoints
| Method | Path | Auth | Request Model | Response Model | Description |
|---|---|---|---|---|---|
| POST | `/sync/supplier/{supplier_id}` | Header secret | Header `x-sync-secret` | JSON | Syncs supplier products from external source into DB. |
| GET | `/suppliers` | No | - | `list[Supplier]` | Fetches all suppliers. |

### Functions
- `sync_supplier_products(supplier_id: str, x_sync_secret: str = Header(None))`
- `get_suppliers()`

---

## 9) Shopify Router (`routers/shopify_routers.py`)
Prefix: `/shopify`

### Endpoints
| Method | Path | Auth | Request Model | Response Model | Description |
|---|---|---|---|---|---|
| GET | `/shopify/install` | No | - | JSON | Generates Shopify OAuth install URL. |
| GET | `/shopify/oauth/callback` | No | Query from Shopify | Redirect | Exchanges code for token, inserts/updates supplier, redirects to status page. |
| POST | `/shopify/sync-products/{supplier_id}` | No | - | JSON | Pulls Shopify products and exports debug JSON/CSV (DB sync currently skipped/commented). |

### Functions
- `shopify_install()`
- `shopify_oauth_callback(request: Request)`
- `sync_shopify_products(supplier_id: str)`

---

## Schemas Reference (`schemas/*.py`)

### Auth and Profile
- `UserCreate`
- `UserLogin`
- `UserForgotPassword`
- `UserResetPassword`
- `UserResponse`
- `ProfileBase`
- `Profile`

### Orders
- `OrderItemCreate`
- `OrderItem`
- `OrderCreate`
- `OrderUpdate`
- `Order`

### Admin
- `DeliveryPartner`
- `PaymentVerificationRequest`
- `Token`
- `BrandResponse`
- `CategoryResponse`
- `CartItem`
- `DeliveryStatusEnum`
- `DeliveryStatusCreate`
- `CouponBase`
- `AdminCouponResponse`
- `AdminCouponCreateRequest`

### Partners
- `PartnerActivateRequest`
- `PartnerCreate`
- `PartnerResponse`
- `PartnerSignupRequest`
- `PartnerLoginRequest`
- `PartnerProfileBase`
- `PartnerDashboardResponse`

### Product
- `Product`
- `ProductUpdate`
- `ProductSimple`

### Returns
- `ReturnTypeEnum`
- `ReturnStatusEnum`
- `ReturnCreate`
- `ReturnUpdate`
- `ReturnResponse`

### Suppliers
- `Supplier`

---

## Service Layer Functions (`services.py`)
- `get_user_supabase(token: str)`
- `get_current_user(token: str = Depends(oauth2_scheme))`
- `fetch_supplier_products()`
- `send_order_email(to_email: str, order_id: int, total_amount: float, items: list)`

### Service Globals / Clients
- `supabase_admin`: service-role client
- `supabase_anon`: anon client
- `supabase_db`: service-role DB client
- `razorpay_client`
- `oauth2_scheme`

---

## Utility Functions (`utils.py`)

### Pricing and Orders
- `calculate_order_pricing(order, validated_items, skip_brand_offers=False)`
- `generate_unique_lucky_numbers(count: int)`

### PDF and Invoice
- `generate_pdf_invoice(order_data, user_data, items_data)`

### Supplier/Shopify Mapping and Upsert
- `map_supplier_product(p: dict, supplier_id: str)`
- `clean_html(html)`
- `map_shopify_product(p: dict, supplier_id: str)`
- `map_shopify_variant(v: dict, product_id: int)`
- `upsert_product(data: dict)`
- `upsert_variant(data: dict)`

### Shopify Debug Export
- `fetch_product_metafields(shop: str, token: str, product_id: int)`
- `dump_shopify_debug(products: list, shop: str, token: str)`

### Enrichment Rules
- `normalize_tags(tags: str) -> set`
- `derive_segment(tags: set) -> str | None`
- `derive_sub_category(tags: set) -> str | None`
- `derive_category_group(category: str) -> str | None`
- `derive_short_description(long_desc: str) -> str | None`
- `build_keywords(row: dict) -> set`
- `enrich_products_csv(input_csv: str, output_csv: str)`

---

## Known Implementation Notes
- `shopify/sync-products/{supplier_id}` currently exports debug files and does not persist products because DB sync block is commented.



---

# 📦 Database Architecture & Business Logic 

This section explains why certain tables exist and how business rules are structured to avoid ambiguity.

---

## 1️⃣ Coupons System Design

All coupons are stored in the `coupons` table.

### 🔹 Coupon Types (Business Categories)

Coupons are classified into two main types:

### 1. Direct Coupons
- Available to all users at checkout
- Not tied to a specific partner
- Can be:
  - Universal (applicable to all brands)
  - Brand-specific

These are visible and usable directly in the checkout flow.

---

### 2. Partner Coupons
- Created for a specific partner (`partner_id`)
- Used to track partner performance
- Can be:
  - Brand-specific
  - Universal (based on configuration)

When a partner coupon is used:
- It is linked to the partner
- It contributes to partner dashboard metrics.

---

### 🔹 Coupon Scope

Each coupon has:

- `offer_scope`
  - `"brand"` → Applies only to a specific brand
  - `"universal"` → Applies to all brands

- `brand_id`
  - Required if scope is `"brand"`
  - `NULL` if universal

---

### 🔹 Coupon Usage Logic

- For **COD orders** → coupon usage increments immediately after order creation.
- For **Online payments** → coupon usage increments only after payment confirmation.
- Coupon increment logic is implemented in an idempotent-safe manner.

---

## 2️⃣ Product & Variant Architecture

The product catalog is normalized into two tables:

---

### 🔹 `products` Table

- Stores base product data.
- Products are grouped by `base_product_id`.
- Products under the same base product represent different **colors**.
- Color variations are handled at product level.



### 🔹 `product_variants` Table

- Stores size-based variants.
- Each variant belongs to a single product.
- Handles inventory per size.

Design Principle:

- **Color → Product level**
- **Size → Variant level**

This keeps inventory and product structure clean and scalable.

---

## 3️⃣ Partners Architecture

The partner system is intentionally separated into two logical layers.

---

### 🔹 `partners` Table

Stores:
- All submitted partner applications
- Registration form details
- Interested users who applied

Includes:
- Pending applications
- Rejected applications
- Approved applications

This acts as the **partner application registry**.

---

### 🔹 `profiles` Table

When admin approves a partner:

- The user's profile is updated:
  - `is_partner = true`
  - `partner_id` is assigned

This activates partner access within the system.

---

### 🔹 `partners_profiles` (If Present)

If used:
- Stores aggregated partner business metrics
- Used for analytics or dashboards
- Not used for authentication

---

## 4️⃣ Orders & Payment Architecture

Orders follow a two-stage payment lifecycle.

---

### 🔹 COD Orders

1. Order created
2. Stock deducted
3. Coupon usage incremented immediately
4. Confirmation email sent immediately

---

### 🔹 Online Payments (Razorpay)

Payment flow (current implementation using `/payment/verify`):

1. Order created → `payment_status = "Pending"`
2. Razorpay checkout popup initiated
3. User completes payment
4. Frontend receives Razorpay success response
5. Frontend calls backend endpoint:
   - `POST /payment/verify`
6. Backend:
   - Verifies Razorpay signature
   - Updates:
     - `payment_status = "Completed"`
     - `order_status = "Confirmed"`
   - Increments coupon usage (if applicable)
   - Dispatches confirmation email (background task)

Important:

- `/payment/verify` depends on authenticated user (`JWT required`)
- Payment confirmation currently relies on frontend calling this endpoint
- Idempotent logic ensures order is not updated twice

---

## 5️⃣ Returns Logic

Returns are allowed only when:

- Order is marked as delivered
- Current time ≤ `return_valid_till`
- Item belongs to the order
- No duplicate return request exists

The return window is set when delivery status is updated to `"Delivered"`.

---

## 6️⃣ Supplier & Shopify Integration

Two external integrations are supported.

---

### 🔹 Supplier Sync

- Pulls products from external supplier API
- Protected via `x-sync-secret` header
- Inserts or updates products in database

---

### 🔹 Shopify Integration

- OAuth-based flow
- Stores supplier access token
- Supports product export for debugging
- DB sync logic can be enabled when required

---

# 🏗 Architectural Design Principles

- Service-role Supabase client used for secure writes
- Row-Level Security (RLS) enforced for user-scoped reads
- Idempotent payment updates
- Background tasks used for email dispatch
- Separation between:
  - Application data
  - Analytics data
  - Authentication data

---

# 🔐 Security Notes

- All sensitive DB writes use `supabase_admin`
- Authenticated endpoints depend on `get_current_user`
- Razorpay webhook verifies signature before DB updates
- SMTP credentials stored only in environment variables

---




