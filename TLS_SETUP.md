# TLS / Domain Setup for EigenClaw TEE

Use this to test whether the platform opens ingress when a verified domain is configured.

## 1. Add TLS variables to `.env`

Append from the example (or copy manually):

```env
# Core Networking
DOMAIN=api.yourdomain.com
APP_PORT=18789

# TEE/Platform Flags
ENABLE_CADDY_LOGS=true
ACME_STAGING=true

# Optional (OpenClaw uses these internally)
GATEWAY_BIND_ADDR=0.0.0.0
GATEWAY_PORT=18789
```

Replace `api.yourdomain.com` with a domain you control. Use `ACME_STAGING=true` first to avoid Let's Encrypt rate limits while testing.

## 2. Create DNS A record

Create an **A record** at your DNS provider:

| Type | Name | Value           | TTL  |
|------|------|-----------------|------|
| A    | api  | 136.115.239.17  | **60** |

**TTL:** Use **60** or **300** seconds so DNS propagates quickly. High TTLs can cause stale caches and TLS challenge failures.

## 3. Wait for DNS propagation

```powershell
# Check propagation (use your actual domain)
nslookup yourdomain.com
```

## 4. Upgrade the app

```powershell
git rev-parse HEAD   # get SHA, then:
ecloud compute app upgrade 0x0c976F51abC812e7f2b1767652085b0588556a94 --env-file .env --verifiable --repo https://github.com/lattibeaudiere/eigenclaw --commit <40-char-SHA> --instance-type g1-standard-4t --log-visibility private --resource-usage-monitoring enable
```

**If debug logs show `DOMAIN=<unset>`:** The platform may not be loading `.env` into KMS. Ensure `.env` has `DOMAIN=api.yourdomain.com` (no spaces around `=`), is in the project root, and is passed via `--env-file .env`.

## 5. Test

Open `https://api.yourdomain.com` in your browser. If TLS and ingress work, you should reach the OpenClaw gateway.

---

## During upgrade: verify ports 80/443

In a **separate terminal** (or from another machine), run these **while the upgrade is in progress** to see if the platform opens ports:

```powershell
# Port 80 (HTTP-01 ACME challenge)
Test-NetConnection -ComputerName 136.115.239.17 -Port 80

# Port 443 (TLS-ALPN-01 ACME challenge)
Test-NetConnection -ComputerName 136.115.239.17 -Port 443
```

Or from Linux/macOS:
```bash
curl -v --connect-timeout 5 http://136.115.239.17/
curl -v --connect-timeout 5 https://136.115.239.17/
```

**If these still timeout:** The platform firewall is blocking; only Layr-Labs can open it.

---

## Check logs for ACME result

After upgrade, run:
```powershell
ecloud compute app logs 0x0c976F51abC812e7f2b1767652085b0588556a94
```

- **"Challenge failed"** or ACME errors → Ports 80/443 are blocked; firewall closed.
- **"Certificate obtained"** or no ACME errors → Cert issued; if domain still unreachable, routing/SNI may be the next hurdle.

---

## If it still times out

The platform may not open ingress even with a domain. Add this to your Layr-Labs GitHub issue:

> "Confirmed the workload remains active as PID 1 with no exits, but the **136.115.239.17** address remains non-routable via ICMP and TCP. Is the platform utilizing an **Attestation-Aware Ingress**? If so, does the infrastructure require a `DOMAIN` environment variable to be present before the edge router will bridge traffic to the enclave?"

## Staging vs production

- **ACME_STAGING=true** — test certs (no rate limits; browsers will warn)
- **ACME_STAGING=false** — production certs (5 certs/week/domain limit)

Switch to production only after confirming it works with staging.
