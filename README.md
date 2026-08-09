# Crypto Trade App

A lightweight web application that simulates a crypto trading bot. The bot automatically trades in Bitcoin, Ethereum and Solana using mock data.

## Architecture Overview
- **Backend** – FastAPI (Python) exposes REST endpoints and runs a background scheduler that updates prices and executes trades.
- **Frontend** – React (Vite + TypeScript) consumes the API and displays live prices, portfolio and trade history.
- **Data persistence** – SQLite via SQLAlchemy; the database is reset on each start for simplicity.
- **Bot logic** – A simple moving‑average crossover strategy runs every minute.
- **Testing** – Pytest for backend logic, Vitest for frontend components.
- **CI/CD** – GitHub Actions run linting and tests on every push.

All dependencies are open‑source, pinned to the latest secure releases and checked with `safety`.
