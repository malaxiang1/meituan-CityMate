# Security Notes

Do not commit local secrets.

Commit:

- `.env.example`
- source code
- docs
- lock files

Do not commit:

- `.env`
- real AMap keys
- real OpenAI-compatible keys
- real merchant API tokens
- exported private merchant datasets

Users who run the project should apply for and configure their own keys:

- `AMAP_WEB_SERVICE_KEY`: AMap Web Service key for geocoding, POI search/detail, and route geometry.
- `OPENAI_API_KEY`: optional OpenAI-compatible LLM key.
- `CITYMATE_VENDOR_API_KEY`: optional authorized merchant API token.
- `CITYMATE_VENDOR_DATA_PATH`: optional local authorized merchant data file path.

If using local Ollama, no LLM key is needed, but users must install/pull their own local model and set:

- `CITYMATE_LLM_PROVIDER=ollama`
- `OPENAI_BASE_URL=http://127.0.0.1:11434/v1`
- `OPENAI_MODEL=gemma3:12b`
