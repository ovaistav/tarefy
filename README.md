# Inventory backend

Django + Django REST Framework backend for the **inventory** tab of the vegetable
seller's Android app.

- No authentication yet (JWT comes later); every endpoint is open.
- All user-facing error messages are in Persian.
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
python manage.py seed_demo        # 12 demo products, safe to run twice
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

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/catalog/products/` | Product list, no pagination |
| GET | `/inventory/loads/?available=true` | Load list; `available=true` hides finished loads |
| POST | `/inventory/loads/` | Create a load (201) |
| POST | `/inventory/loads/{id}/finish/` | Mark a load finished (idempotent, 200) |
| POST | `/inventory/loads/{id}/restore/` | Make a load available again (idempotent, 200) |

Every `409` has the same shape so the app can branch on `code`:

```json
{ "code": "stale_state", "detail": "وضعیت بارها تغییر کرده است. لطفاً دوباره تلاش کنید." }
```

`code` is either `stale_state` (the client's view is outdated — refetch) or
`restore_conflict` (another available load already holds that label).

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

### List loads

```bash
# only the loads that are still available
curl -s "$BASE/inventory/loads/?available=true"

# every load, finished ones included
curl -s "$BASE/inventory/loads/"
```

```json
[
  { "id": 1, "product": 1, "product_name": "خیار", "label": "الف" },
  { "id": 2, "product": 1, "product_name": "خیار", "label": "ب" }
]
```

### Create a load

First load of a product — the label is optional:

```bash
curl -s -X POST $BASE/inventory/loads/ \
  -H 'Content-Type: application/json' \
  -d "{\"product\": $PRODUCT_ID}"
```

```json
{ "id": 1, "product": 1, "product_name": "خیار", "label": "" }
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
{ "id": 2, "product": 1, "product_name": "خیار", "label": "ب" }
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
{ "id": 1, "product": 1, "product_name": "خیار", "label": "الف" }
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
{ "id": 1, "product": 1, "product_name": "خیار", "label": "الف" }
```

## Notes for the Android client

- Labels are normalized on the server: trimmed, internal whitespace collapsed, and
  Arabic `ي`/`ك` converted to Persian `ی`/`ک`. `"يک"` and `"یک"` are the same label.
- A load is available exactly when `finished_at` is `NULL`; there is no separate
  "available load" model.
- Among available loads a product cannot have two loads with the same label — two
  empty labels conflict too. Finished loads are excluded from the rule.
- Creating a load touches the product's `updated_at`, which moves that product to
  the front of `/catalog/products/`.
- When a POST races another request, the database constraint turns it into a `409`
  `stale_state`; retry after refetching.

## Admin

`/admin/` can manage products (with image upload), suppliers, goods receipts and
loads by hand. The loads list can be filtered by product and by whether the load is
finished.
