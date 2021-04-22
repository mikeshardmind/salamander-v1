Example systemd service files:

/etc/systemd/system/salamander.service
```
[Unit]
Description=Salamander
After=multi-user.target
After=network-online.target
After=hydra.service
Wants=network-online.target

[Service]
WorkingDirectory=/umw/salamander
User=umw
Group=umw
ExecStart=/umw/salamander/.venv/bin/python -O runner.py
Type=idle
Restart=always
RestartSec=10
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
```

/etc/systemd/system/hydra.service
```
[Unit]
Description=Hydra
After=multi-user.target
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/umw/hydra
User=umw
Group=umw
ExecStart=/umw/hydra/.venv/bin/python -O hydra.py
Type=idle
Restart=always
RestartSec=10
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
```

/etc/systemd/system/basilisk.service
```
[Unit]
Description=Basilisk
After=multi-user.target
After=network-online.target
After=hydra.service
Wants=network-online.target
[Service]
WorkingDirectory=/umw/basilisk
User=umw
Group=umw
ExecStart=/umw/basilisk/.venv/bin/python -O basilisk.py
Type=idle
Restart=always
RestartSec=10
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
```

You can set the enviromnent for salamander with `systemctl edit salamander.service`

Filling with:

```
[Service]
Environment=SALAMNDER_TOKEN=XXX
```