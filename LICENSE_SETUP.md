# Licence activation and server setup

## Licence server

The Node server is the authority for licence status, customer-name matching,
expiry, and one-device binding. It persists records either in MongoDB
(`MONGODB_URI`) or in the JSON file selected by `DATA_FILE`. Use a durable
MongoDB deployment or persistent disk for production; an ephemeral server
filesystem can lose its JSON database when the host restarts or redeploys.

1. Install Node.js, then run `npm ci`.
2. Copy `.env.example` to `.env` and set a unique `ADMIN_TOKEN` with at least
   32 characters. Keep `.env` private and out of source control.
3. Configure `MONGODB_URI` for a durable production database and set
   `NODE_ENV=production`. For a local development server, leave it unset and
   choose a durable `DATA_FILE`.
4. Run `npm start`; open `/admin` on the server to manage licences.

Admin API operations require the bearer token. The browser asks for it at
login; it is held in session storage only for that browser tab session.
Generated keys are random and stored as records with stable licence IDs.
Existing records that only have a `label` are migrated to customer names
without deleting their history.

## Desktop application

Install Python dependencies with `pip install -r requirements.txt`, plus the
Playwright browser/runtime required by the existing application (for source
runs, install its Chromium browser with `playwright install chromium`). To
rebuild the Windows executables, run PyInstaller with each existing `.spec`
file from the project directory. The client
uses the configured `LICENSE_URL` and pinned Ed25519 `PUBLIC_KEY` in
`license_check.py`; when deploying a new server, update both values in the
desktop build from the server URL and `/api/public-key`. The public signing
key is not a credential. Never put the server's private signing key or
`ADMIN_TOKEN` in the desktop app.

Copy `data.example.txt` to `data.txt` and add your own records before running
the automation. `data.txt` and output files are local user data and are
intentionally excluded from Git.

On first launch the app asks for the customer name and licence key. Name
matching uses Unicode NFKC normalization, trims and collapses whitespace,
and ignores case. On Windows, the saved activation session is protected by
Windows DPAPI. Later launches revalidate with the server; a signed cache
allows operation for up to 12 hours during a network outage.

## Security limitations

The central server database is the trusted source for activation and device
binding. The client uses a hash of the platform machine identifier as its
device fingerprint; the server stores and checks that fingerprint, so copying
only the licence key to another PC does not activate it. An administrator
can revoke, renew, delete, or reset the binding from the protected panel.

No client-side desktop protection is tamper-proof. A local administrator can
modify the executable, spoof machine identifiers, or copy a complete machine
profile. DPAPI protects saved activation data from casual file editing, not
from a determined owner of the PC. When offline, revocations and binding
resets cannot be learned until the server is reachable, and the signed cache
can permit up to 12 hours of continued access. Use an online server with
durable, access-controlled storage for enforcement; a fully offline
file-backed server has weaker availability and tamper guarantees.

## Validation

Run the existing and licence integration tests with:

```powershell
python -m unittest discover -s tests -v
```

The licence integration test starts a temporary local server with an isolated
database and test-only admin token. It does not access the configured hosted
licence service or modify its records.
