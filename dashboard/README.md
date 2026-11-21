# ShiftWise dashboard (Flutter)

A live view of the ShiftWise agent. It shows every step the LangGraph agent takes while it works:

- **Live run**: the agent graph with per-node state, run counts and timings; the raw event stream
  (extraction attempts, CP-SAT results, routing decisions with their reason, relaxations); the
  constraints as extracted vs as finally used; the schedule grid (dropped days off are outlined in red);
  load per employee; coverage per shift; the explanation; and the independent validator's verdict.
- **Evaluation**: the measured results in `../evaluation/results/` (solver benchmark, relaxation stress
  test, LLM evaluation with per-request outcomes).
- **How it works**: the architecture and what is (and is not) guaranteed.

Two input modes: plain language (the LLM extracts the problem) or structured. Structured mode skips
the LLM entirely, so it works without a Gemini key or when the provider is overloaded.

## Run

Start the API from the project root, then the dashboard:

```bash
uvicorn api:app --reload                 # http://localhost:8000
cd dashboard
flutter pub get
flutter run -d chrome                    # or: flutter run -d chrome --dart-define=API_URL=http://host:8000
```

Demo links: `?demo=1` starts the structured example on load; `?tab=evaluation` or `?tab=about` opens
a tab directly.

Production build:

```bash
flutter build web --release --no-web-resources-cdn
python -m http.server 8080 --directory build/web
```

If the project sits in a OneDrive folder, OneDrive can lock `build/` while it syncs. Build outside it
with `--output <dir>`.

## How it gets the events

`POST /plan/stream` and `POST /solve/stream` return Server-Sent Events. On the web, the default
`http` client buffers the whole response, so `lib/api/streaming_client_web.dart` uses `fetch` (through
the `fetch_client` package) to read events as they arrive. The API allows CORS from `localhost` and
`127.0.0.1` on any port by default. To serve the dashboard from elsewhere, set
`SHIFTWISE_CORS_ORIGINS` to a comma-separated list of origins (it replaces the default).

## Code map

| Path | Role |
|---|---|
| `lib/api/` | JSON models mirroring the Pydantic schema, API client, SSE decoder |
| `lib/state/run_controller.dart` | turns the event stream into node states, problem versions and the result |
| `lib/widgets/` | pipeline graph, event timeline, schedule grid and charts, request form, result cards |
| `lib/screens/` | the three tabs |
| `test/` | parsing, SSE decoding, form parsing, and full-app widget tests in wide and narrow layouts, fed with an event stream recorded from the real backend (`test/fixtures/`) |

```bash
flutter analyze && flutter test
```
