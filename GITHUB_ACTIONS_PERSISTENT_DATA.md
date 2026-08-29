# Amazon GitHub Actions — Persistent Master Data

## Run command

The workflow runs:

`python main.py --batch --headless`

## Persistent files

After a successful scraper run, GitHub Actions commits these files back to the `main` branch:

- `output/Amazon_Seller_Master_Data.xlsx`
- `amazon_sellers.db`

Therefore the Master Excel and SQLite database remain in the repository for the next run.

## Logs

Logs and debug files are uploaded as a GitHub Actions artifact and are not committed to the repository.

## Manual run

GitHub → Actions → Amazon Playwright Scraper → Run workflow

## Scheduled run

The workflow is configured for 09:00 IST daily (`03:30 UTC`).

## Important

The repository workflow requires `contents: write`, which is already configured.

The workflow commits data only when the scraper job succeeds, preventing a failed scrape from overwriting/committing incomplete data.
