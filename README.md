# Inventory backend

Django + Django REST Framework backend for the **inventory**, **sales** and
**parties** tabs of the vegetable seller's Android app.

- No authentication yet (JWT comes later); every endpoint is open.
- All user-facing error messages are in Persian.
- All money is an integer number of Rial in a `BigInteger`; no floats anywhere.
- SQLite for development.

## Setup

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo        # 12 products, 3 banks, 5 parties; safe to run twice
```

Run the tests:

```bash
python manage.py test
```

## Running the server for the Android emulator

The emulator cannot reach `localhost` on the host, so bind the dev server to all
interfaces and use `10.0.2.2` (the emulator's alias for the host machine) as the
base URL in the app:

```bash
python manage.py runserver 0.0.0.0:8000
```

- Emulator: `http://10.0.2.2:8000/`
- Physical device on the same Wi-Fi: `http://<your-pc-lan-ip>:8000/`

`ALLOWED_HOSTS = ["*"]` and the development `SECRET_KEY` in
`config/settings.py` are for local development only — change both before deploying.

## Endpoints

### Catalog and inventory

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/catalog/products/` | Product list, no pagination |
| GET | `/inventory/loads/?available=true` | Loads grouped by product name; `available=true` hides finished loads |
| POST | `/inventory/loads/` | Create a load (201) |
| PATCH | `/inventory/loads/{id}/` | Change `label` and `tare_weight` only |
| DELETE | `/inventory/loads/{id}/` | Delete a load (204), or 409 `in_use` |
| POST | `/inventory/loads/{id}/finish/` | Mark a load finished (idempotent, 200) |
| POST | `/inventory/loads/{id}/restore/` | Make a load available again (idempotent, 200) |

### Parties and accounting

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/parties/?q=` | Party list `{id, name, label}`, no pagination; `q` matches name **or** label |
| POST | `/parties/` | Create a party (201) |
| GET | `/parties/{id}/` | Full party |
| PATCH | `/parties/{id}/` | Update a party |
| DELETE | `/parties/{id}/` | Delete a party (204), or 409 `in_use` if anything references it |
| GET | `/accounting/banks/` | `[{id, name}]` by name; read only |

### Sales

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/sales/?status=&party=&cursor=` | Cursor-paginated list, 30 per page |
| POST | `/sales/` | Create a draft with its invoice and porterage (201) |
| GET | `/sales/{id}/` | Full sale detail |
| DELETE | `/sales/{id}/` | Delete a draft (204), or 409 `not_deletable` |
| POST | `/sales/{id}/lines/` | Add a line (201, full sale) |
| PATCH / DELETE | `/sales/{id}/lines/{lid}/` | Change (may move the load) or remove a line (full sale) |
| PUT | `/sales/{id}/porterage/` | Set the porterage amount exactly |
| POST | `/sales/{id}/payments/` | Add a payment (201, full sale) |
| PATCH / DELETE | `/sales/{id}/payments/{pid}/` | Change or remove a payment (full sale) |
| PUT / DELETE | `/sales/{id}/account/` | Set or clear the single account party |
| POST | `/sales/{id}/finalize/` | Close the sale (200) |
| GET / PATCH | `/sales/porterage-settings/` | The single porterage settings row |

Every `409` has the same shape so the app can branch on `code`:

```json
{ "code": "stale_state", "detail": "وضعیت بارها تغییر کرده است. لطفاً دوباره تلاش کنید." }
```

`code` is one of:

| Code | Meaning |
| --- | --- |
| `stale_state` | The client's view of the loads is outdated — refetch. |
| `restore_conflict` | Another available load already holds that label. |
| `in_use` | The load is on an invoice line and cannot be deleted. |
| `not_deletable` | Only a draft sale can be deleted. |
| `load_finished` | The load is finished and can no longer be sold. |
| `not_settled` | Finalize was refused; the body also carries `remaining`. |
| `no_lines` | Finalize was refused because the sale has no lines. |

## curl examples

In the examples below `$PRODUCT_ID` is a product id from
`GET /catalog/products/` (e.g. `PRODUCT_ID=1`).

```bash
BASE=http://127.0.0.1:8000
PRODUCT_ID=1
```

### Catalog

```bash
curl -s $BASE/catalog/products/
```

```json
[
  {
    "id": 1,
    "name": "خیار",
    "image_url": null,
    "updated_at": "2026-10-01T13:20:43.684689+03:30"
  }
]
```

`image_url` is an absolute URL with `?v=<int>` appended. The version comes from
`image_updated_at` (not `updated_at`) because the app uses it as an image cache key,
so it only changes when the image itself changes.

`name` is unique: loads are grouped by it, so one name can only mean one product.

### List loads

```bash
# only the loads that are still available
curl -s "$BASE/inventory/loads/?available=true"

# every load, finished ones included
curl -s "$BASE/inventory/loads/"
```

```json
{
  "خیار": {
    "product": 1,
    "sticker": "cucumber",
    "background": "#2E7D32",
    "loads": [
      { "id": 1, "product": 1, "product_name": "خیار", "label": "الف", "tare_weight": "0.000" },
      { "id": 2, "product": 1, "product_name": "خیار", "label": "ب", "tare_weight": "0.000" }
    ]
  }
}
```

The list is grouped by product name so the app can draw one tile per product with
the loads it still offers. `sticker` and `background` belong to the product and are
repeated in every group, so a tile never needs a second request. A product with no
matching load has no key at all. Product names are unique, so a key always points
at exactly one product.

### Update a load

Only `label` and `tare_weight` may change; the product is immutable.

```bash
curl -s -X PATCH $BASE/inventory/loads/1/ \
  -H 'Content-Type: application/json' \
  -d '{"label": "  ب   الف ", "tare_weight": "1.000"}'
```

```json
{ "id": 1, "product": 1, "product_name": "خیار", "label": "ب الف", "tare_weight": "1.000" }
```

Moving a load to another product is a `400`:

```json
{ "product": ["کالای بار قابل تغییر نیست."] }
```

A blank label is only allowed while the load is the only available one of its
product; otherwise the creation rules apply — a `400` field error on a clear
duplicate, `409 stale_state` when the database constraint wins the race.

### Delete a load

```bash
curl -s -X DELETE $BASE/inventory/loads/1/     # 204, no body
```

Once the load is on an invoice line it is history:

```json
{ "code": "in_use", "detail": "این بار در یک فروش استفاده شده است و قابل حذف نیست." }
```

### Create a load

First load of a product — the label is optional:

```bash
curl -s -X POST $BASE/inventory/loads/ \
  -H 'Content-Type: application/json' \
  -d "{\"product\": $PRODUCT_ID}"
```

```json
{ "id": 1, "product": 1, "product_name": "خیار", "label": "", "tare_weight": "0.000" }
```

A second load while the first one is still unlabeled must be rejected, because the
client did not report the unlabeled load it is holding:

```bash
curl -s -X POST $BASE/inventory/loads/ \
  -H 'Content-Type: application/json' \
  -d "{\"product\": $PRODUCT_ID, \"label\": \"الف\"}"
```

```json
{ "code": "stale_state", "detail": "وضعیت بارها تغییر کرده است. لطفاً دوباره تلاش کنید." }
```

The client must then resend **exactly** the currently unlabeled loads — same ids, no
more and no fewer — along with the new label:

```bash
curl -s -X POST $BASE/inventory/loads/ \
  -H 'Content-Type: application/json' \
  -d "{\"product\": $PRODUCT_ID, \"label\": \"ب\",
       \"existing_labels\": [{\"id\": 1, \"label\": \"الف\"}]}"
```

```json
{ "id": 2, "product": 1, "product_name": "خیار", "label": "ب", "tare_weight": "0.000" }
```

Once every available load has a label, the next POST carries only a new label:

```bash
curl -s -X POST $BASE/inventory/loads/ \
  -H 'Content-Type: application/json' \
  -d "{\"product\": $PRODUCT_ID, \"label\": \"ج\"}"
```

Duplicate label for the same product — `400` with a field error:

```bash
curl -s -X POST $BASE/inventory/loads/ \
  -H 'Content-Type: application/json' \
  -d "{\"product\": $PRODUCT_ID, \"label\": \"ب\"}"
```

```json
{ "label": ["برچسب بارهای یک کالا باید یکتا باشد."] }
```

A missing label while other loads already exist is rejected the same way:

```bash
curl -s -X POST $BASE/inventory/loads/ \
  -H 'Content-Type: application/json' \
  -d "{\"product\": $PRODUCT_ID}"
```

```json
{ "label": ["برچسب همه بارهای موجود باید وارد شود."] }
```

### Finish and restore

```bash
curl -s -X POST $BASE/inventory/loads/1/finish/
curl -s -X POST $BASE/inventory/loads/1/finish/    # again: 200, nothing changes
curl -s -X POST $BASE/inventory/loads/9999/finish/ # 404
```

```json
{ "id": 1, "product": 1, "product_name": "خیار", "label": "الف", "tare_weight": "0.000" }
```

Because finished loads are history, a finished load's label can be reused by a new
load (the unique constraint only covers available loads).

Restoring is rejected while another available load holds the same label:

```bash
curl -s -X POST $BASE/inventory/loads/1/restore/
```

```json
{ "code": "restore_conflict", "detail": "بار دیگری با همین برچسب موجود است." }
```

Finish that other load and the restore succeeds:

```bash
curl -s -X POST $BASE/inventory/loads/2/finish/
curl -s -X POST $BASE/inventory/loads/1/restore/
```

```json
{ "id": 1, "product": 1, "product_name": "خیار", "label": "الف", "tare_weight": "0.000" }
```

## Notes for the Android client

### Catalog

- `sticker` is a key into an asset the app ships with (`[a-z0-9_-]`, max 40).
- `background` is a hex color; `#RGB` and `#RRGGBB` are accepted, with or without
  the `#`, and always come back as uppercase `#RRGGBB`.

### Loads

- Labels are normalized on the server: trimmed, internal whitespace collapsed, and
  Arabic `ي`/`ك` converted to Persian `ی`/`ک`. `"يک"` and `"یک"` are the same label.
- A load is available exactly when `finished_at` is `NULL`; there is no separate
  "available load" model.
- Among available loads a product cannot have two loads with the same label — two
  empty labels conflict too. Finished loads are excluded from the rule.
- Creating a load copies `Product.tare_weight` into `Load.tare_weight`, so a later
  change to the product default never rewrites an existing load.
- Creating a load touches the product's `updated_at`, which moves that product to
  the front of `/catalog/products/`.
- When a POST races another request, the database constraint turns it into a `409`
  `stale_state`; retry after refetching.

### Parties

- `name` and `label` together are unique, and both are normalized before saving, so
  `"رضايي"` and `"رضایی"` can never become two parties. `label` keeps its API name —
  what the app shows the user, and what the errors say, is **«توصیف»**. A blank one
  gives `{"label": ["توصیف الزامی است."]}`; a duplicate pair gives
  `{"non_field_errors": ["طرف حسابی با همین نام و توصیف قبلاً ثبت شده است."]}`.
- There is no `description` field (migration `parties.0003`); free-form notes go in
  `details`. Sending `description` is silently ignored.
- `national_code` is stored as `NULL` (never `""`) when absent, which is why many
  parties may lack one. When present it is validated with the official Iranian
  checksum.
- `account_number` (nullable, max 20) is normalized exactly like `phone`: Persian
  digits become ASCII and spaces are dropped. It is deliberately **not** unique and
  carries no checksum — one account may serve several parties, and the server does
  not know which banks exist. Note that both optional number columns store `""`
  rather than `NULL` for a value that was never filled in, so treat `null` and `""`
  alike.
- `details` is a free-form map of short strings to short strings (max 50 keys, key
  length 50, value length 500). The server never interprets the keys — bank account
  number, origin and friends live in the app.
- `DELETE /parties/{id}/` returns 204 when nothing references the party, and 409
  `in_use` when something does. Both `sales.Invoice.buyer` (PROTECT) and
  `inventory.Load.supplier` (SET_NULL) count as references — the check walks the
  reverse relations, so a FK added to Party later is covered automatically. There is
  no soft delete.

### Sales

- The server is the authority. The client sends weights, quantities and rates; the
  server returns `net_weight`, `line_total`, `total_amount` and `summary`.
- `net_weight = gross_weight - load.tare_weight * quantity` and must be above zero.
- `total_amount = sum(line_total) + porterage.amount`.
- `remaining = total_amount - paid - account`. A sale can only be finalized once
  `remaining` is zero.
- Porterage follows the **gross** weight and moves incrementally: adding a line
  adds its whole gross weight, removing subtracts it, and editing applies only the
  difference. Changing just a quantity or a rate leaves it alone. With
  `works_with_porters` off the server never touches it.
- Any edit to a finalized sale flips it back to `draft` in the same transaction.
  Reading a sale never does.
- Every mutation locks the sale row, so concurrent edits serialize instead of
  interleaving.

## Admin

`/admin/` can manage products (with image upload), parties, banks, sales (with
their invoice, lines and payments) and the porterage settings by hand. The loads
list can be filtered by product and by whether the load is finished. The porterage
settings row can neither be added nor deleted — `seed_demo` or the first API read
creates it.
