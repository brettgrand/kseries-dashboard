# Series Dashboard

Small Flask dashboard that fetches the latest archived `kernel-series.yaml` snapshot from `https://kernel.ubuntu.com/info/` and renders a quick overview plus the raw YAML payload.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug
```

Open `http://127.0.0.1:5000/`.