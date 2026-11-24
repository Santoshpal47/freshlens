# FreshLens raw landing zone

Append-only, gzip-compressed API pages exactly as data.gov.in returned them. This is the source of truth;
the Delta lake can always be rebuilt from it (`freshlens rebuild`). The nightly GitHub Action adds one
`daily/ingest_date=YYYY-MM-DD/` folder per day.
