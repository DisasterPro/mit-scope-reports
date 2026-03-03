# MitScope Weekly Reports

Automated weekly production analytics for the Encircle Mitigation Scope service.

Every Sunday at midnight ET, a GitHub Actions workflow:
1. Fetches the past 7 days of production trace data from Langfuse
2. Generates usage, cost/latency, and error analytics
3. Publishes an interactive HTML report to GitHub Pages
4. Posts a summary with the report link to Slack (`#mit-scope-usage`)

## View the Report

**Latest:** https://disasterpro.github.io/mit-scope-reports/

Historical reports are archived at `/archive/YYYY-MM-DD.html`.

## Run Locally

```bash
pip install -r requirements.txt

export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_HOST="https://us.cloud.langfuse.com"

python -m src
```

Output goes to `reports/index.html`.

## Secrets

Configure these in the repo's Settings > Secrets:

| Secret | Description |
|--------|-------------|
| `LANGFUSE_PUBLIC_KEY` | Langfuse API public key |
| `LANGFUSE_SECRET_KEY` | Langfuse API secret key |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook for `#mit-scope-usage` |
