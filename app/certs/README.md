# Certificates

| File | What | Source | SHA-256 |
|---|---|---|---|
| `rds-global-bundle.pem` | 108 Amazon RDS root CA certificates (all regions) | `https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem` (AWS's official trust store), downloaded 2026-09-27 | `e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3` |

Used with `DB_SSLMODE=verify-full` and `DB_SSLROOTCERT=/srv/app/certs/rds-global-bundle.pem`, so the app
checks that it is really talking to our RDS instance (not just that the connection is encrypted).
These are public certificates, not secrets.
