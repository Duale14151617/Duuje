# ARMY HQ — Windows 11 + Docker Desktop (local demo)

This setup runs the React frontend, Django API, and PostgreSQL database together on your own PC. It is for synthetic demo data only, not real personnel or operational records.

## 1. Install Docker Desktop
1. Download Docker Desktop for Windows: https://www.docker.com/products/docker-desktop/
2. Run the installer. Keep the WSL 2 backend option enabled if offered.
3. Restart Windows if asked, open Docker Desktop, and wait until it says Docker is running.
4. Open PowerShell and check:
   ```powershell
   docker --version
   docker compose version
   ```

## 2. Extract this ZIP
Extract the entire ZIP into a folder, for example `C:\ARMYHQ`. Open that folder in File Explorer. You should see `Dockerfile`, `docker-compose.yml`, `docker-compose.local.yml`, `frontend`, and `backend` in the `armyhq-v2.1.2` folder.

## 3. Open PowerShell in the project root
In File Explorer, open the `armyhq-v2.1.2` folder. Click the address bar, type `powershell`, and press Enter. Confirm `dir` shows `Dockerfile` and `docker-compose.local.yml`.

## 4. Start the complete app
Use a demo-only password (at least 12 characters). You can set one in this PowerShell window:

```powershell
$env:ARMYHQ_DEMO_PASSWORD = "Demo-Only-Change-123!"
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build -d
```

The first build downloads packages and may take several minutes. The app container runs database migrations, creates the cache table, seeds reference data, and creates synthetic demo accounts. Wait for it to finish.

## 5. Open ARMY HQ
Open this address in your browser:

http://localhost:8000

The API health endpoint is:

http://localhost:8000/api/v1/health/live/

## 6. Demo login
The seed command creates synthetic accounts including `demo.hqadmin`, `demo.hqreports`, `demo.auditor`, `demo.bari.chief`, and `demo.readonly`. They use the `ARMYHQ_DEMO_PASSWORD` value set above. Privileged roles require authenticator-app MFA enrollment on first sign-in. Use only the synthetic demo accounts.

## 7. Useful Docker commands
View logs:
```powershell
docker compose -f docker-compose.yml -f docker-compose.local.yml logs -f app
```
Stop the app but keep the database:
```powershell
docker compose -f docker-compose.yml -f docker-compose.local.yml down
```
Start it again:
```powershell
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```
Stop and DELETE the database volume (this permanently deletes local demo data):
```powershell
docker compose -f docker-compose.yml -f docker-compose.local.yml down -v
```

## Troubleshooting
- If Docker commands say the daemon is unavailable, open Docker Desktop and wait for it to finish starting.
- If port 8000 is already in use, change the left side of `127.0.0.1:8000:10000` in `docker-compose.local.yml` to `127.0.0.1:8080:10000`, restart, and visit `http://localhost:8080`.
- If startup fails, inspect logs with the logs command above. Share only the relevant error lines; redact passwords, secret keys, and connection strings.
- To rebuild after source changes: `docker compose -f docker-compose.yml -f docker-compose.local.yml up --build -d`.

## Security notes
- This configuration binds the web port to your own PC (`127.0.0.1`), not the public internet.
- Demo database credentials are intentionally local-only and insecure; never reuse them on a server.
- Do not add real personnel, security, medical, or operational information.
- This package has not been verified on your PC; the first Docker build and startup still need to be tested.
