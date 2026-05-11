# smart-hotel-agent

An AI-powered hotel search and reservation assistant built with [Streamlit](https://streamlit.io) and [Google ADK](https://google.github.io/adk-docs/). Uses Gemini 2.5 Flash to search for hotels via Google Search and guides users through a conversational, multi-step booking flow.

## Overview

The app is built around two LLM agents:

- **hotel_search_agent** — queries Google Search for hotels matching the user's request, parses results into structured JSON, and enriches each property with simulated price comparison data from 8 booking platforms (Booking.com, Agoda, MakeMyTrip, Trivago, Hotels.com, Expedia, Goibibo, Cleartrip).
- **booking_agent** — manages a step-by-step reservation flow: room selection → check-in/out dates → guest count → confirmation.

Both agents run on `gemini-2.5-flash` via Google ADK's `LlmAgent` backed by an `InMemorySessionService`.

## Stack

| Layer | Technology |
|---|---|
| Frontend | Streamlit |
| LLM / Agents | Google ADK (`google-adk`), Gemini 2.5 Flash |
| Model wrapper | LiteLLM |
| Data validation | Pydantic v2 |
| Session state | In-memory (no persistence) |

## Prerequisites

- Python 3.10+
- A valid [Google AI Studio API key](https://aistudio.google.com/app/apikey) with access to `gemini-2.5-flash`

## Setup

```bash
git clone https://github.com/your-username/smart-hotel-agent.git
cd smart-hotel-agent

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

Set your API key as an environment variable (do not hardcode it in source files):

```bash
export GOOGLE_API_KEY="your_api_key_here"
```

## Running

```bash
python -m streamlit run agent.py
```

Opens at `http://localhost:8501` by default.

## Usage

| Intent | Example prompt |
|---|---|
| Search hotels | `Find hotels in Miami under $200` |
| Begin booking | `Book The Leela Palace` |
| Select room type | `Executive Suite` |
| Provide dates | `Check-in: 2025-08-01, Check-out: 2025-08-03` |
| Specify guests | `2 guests` |
| Confirm reservation | `confirm` |

## Project structure

```
.
├── agent.py          # All application logic and Streamlit UI
├── requirements.txt  # Python dependencies
└── README.md
```

## Notes

- Hotel prices are **simulated** using randomised mock data. No real booking API is integrated.
- Sessions are in-memory only and reset on app restart.
- The `google_search` tool requires your Google AI project to have the Generative Language API enabled.

## Potential extensions

- Integrate real hotel inventory APIs (Booking.com Affiliate, Amadeus, RateHawk)
- Persistent session storage (SQLite or Postgres via SQLAlchemy)
- Authentication layer for multi-user support
- Email confirmation via SendGrid or SMTP
- Server-side rate limiting and retry logic for quota management
