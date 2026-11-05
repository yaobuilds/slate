# Security notes

Slate is meant for a home network. It is not built to face the internet. Do not forward port 8000 on your router.

## The Wi-Fi PIN

- With `--lan`, the server listens on the local network. On the host itself (`127.0.0.1`) private views need no PIN. On the network they do.
- The PIN is 4 to 8 digits and is checked against a strict pattern before use.
- The submitted PIN and the stored PIN are both hashed with SHA-256 and compared with `hmac.compare_digest`, so the comparison time does not reveal how many digits matched.
- A correct PIN sets a session cookie: `HttpOnly`, `SameSite=Lax`, valid for 7 days. **Sign out on Wi-Fi** in Settings clears it.
- Rate limit: 5 wrong PINs from one IP address lock that address out for 60 seconds. The count is kept in memory per IP.
- `pin.local` is created with owner-only permissions and is gitignored.

The PIN travels over plain HTTP on your own network, so treat it as a convenience lock, not strong security.

## Files

- Request paths are normalized and checked against an allow-list. Traversal attempts (`..`, backslashes, null bytes) get no file.
- Local-only files are not served: PIN, TV certificate, settings, calendar cache, and uploaded photos.
- Responses send `X-Content-Type-Options: nosniff`, and private data is sent with `Cache-Control: no-store`.
- Photo uploads have size, count, and total-size limits, and the server checks the real file type (JPEG, PNG, GIF, WebP, HEIF) instead of trusting the file name.

## Secrets

- Calendar OAuth values live in the macOS Keychain.
- The optional map key lives in `carto.local` or an environment variable, and the server fetches tiles on the page's behalf.
- The TomTom key lives in `tomtom.local` or `SLATE_TOMTOM_KEY`, and the server calls TomTom itself.
- Nothing secret is committed. If you find something that looks like it, please open an issue.

## Reporting a problem

Open a GitHub issue. If it involves a secret, describe it without pasting the secret.
