# TickerBoo Deployment Guide

Target: `https://tmc.vetami.net/tb`

## First deploy (server setup)

```bash
# 1. Clone the repo
git clone https://github.com/econodoo/tickerboo.git
cd tickerboo

# 2. Create virtualenv and install deps
python3 -m venv backend/venv
backend/venv/bin/pip install --upgrade pip
backend/venv/bin/pip install -r backend/requirements.txt

# 3. Create .env
cp .env.example .env
nano .env   # set TICKERBOO_ENV=prod and any other values

# 4. Create data/logs dirs
mkdir -p data logs

# 5. Test launch manually first
bash scripts/launch_server.sh
# → should print "Starting TickerBoo prod on 127.0.0.1:8688"
# → curl http://localhost:8688/health   should return {"status":"ok"}
# Ctrl+C to stop

# 6. Install systemd service
nano systemd/tickerboo.service   # set correct WorkingDirectory and ExecStart paths
sudo cp systemd/tickerboo.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tickerboo
sudo systemctl start tickerboo
sudo systemctl status tickerboo

# 7. Wire up nginx
# Paste the location block from nginx/tickerboo.conf into your tmc.vetami.net server block
sudo nginx -t && sudo systemctl reload nginx

# 8. Verify end-to-end
curl https://tmc.vetami.net/tb/health
```

## Updating (every time code changes)

```bash
# On the server — pull and restart
cd ~/tickerboo
git pull
sudo systemctl restart tickerboo
sudo systemctl status tickerboo   # confirm it came back up
```

That's it. No zip, no SFTP. Git pull does the diff.

## Dev machine setup

```bash
git clone https://github.com/econodoo/tickerboo.git
cd tickerboo
bash backend/run.sh
# → http://localhost:8688/health
# → http://localhost:8688/docs
```

To pull latest changes from Claude's pushes:
```bash
git pull
bash backend/run.sh   # --reload is on, so restart only needed for dependency changes
```

## Dependency changes

If `requirements.txt` changed after a pull:
```bash
# Dev
source backend/venv/bin/activate
pip install -r backend/requirements.txt

# Server
backend/venv/bin/pip install -r backend/requirements.txt
sudo systemctl restart tickerboo
```

## Logs

```bash
# Systemd journal (live)
sudo journalctl -u tickerboo -f

# App log file (live)
tail -f logs/tickerboo.log

# Last 100 lines
tail -100 logs/tickerboo.log
```

## Useful checks

```bash
# Is it running?
sudo systemctl status tickerboo

# What port is it on?
ss -tlnp | grep 8688

# Health
curl http://localhost:8688/health
curl https://tmc.vetami.net/tb/health
```
