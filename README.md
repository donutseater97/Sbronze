# Sbronze
Sbronze Treasure Hunt

## Deployment notes

- The app reads cached historical prices from `historical_data.csv`; it does not call Yahoo Finance directly in Streamlit.
- `funds.csv` changes trigger a GitHub Actions workflow that regenerates `historical_data.csv` (see `.github/workflows/update-historical-data.yml`).

## Required secrets (Streamlit Cloud)

Set these in your Streamlit app secrets (or environment variables):

- `GITHUB_TOKEN`: Personal access token with **Contents: Read and write** for this repo
- `GITHUB_REPO`: `donutseater97/Sbronze`
- `GITHUB_BRANCH` (optional): `main`

## Workflows

- Auto refresh runs daily at 05:00 UTC and on `funds.csv` changes.
- Workflow file: `.github/workflows/update-historical-data.yml`

## Updating funds

- Use the “➕ Add Fund” form in the app. It saves locally and attempts to push `funds.csv` to GitHub. If push fails, check token/permissions.
