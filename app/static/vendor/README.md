# Vendored files

| File | Version | Source | License | SHA-256 |
|---|---|---|---|---|
| `chart.umd.min.js` | Chart.js 4.5.1 | `https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js` (official npm package) | MIT | `48444a82d4edcb5bec0f1965faacdde18d9c17db3063d042abada2f705c9f54a` |

Downloaded 2026-09-27. The hash matched the one jsdelivr publishes for the npm package
(`data.jsdelivr.com/v1/packages/npm/chart.js@4.5.1`). It is served from this app rather than a
CDN so the dashboard's Content-Security-Policy can allow scripts from this site only.

Check it (PowerShell):  `(Get-FileHash app\static\vendor\chart.umd.min.js).Hash`
