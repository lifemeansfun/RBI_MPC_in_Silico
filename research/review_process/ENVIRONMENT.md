# Execution environment

Environment observed on 5 October 2026: macOS, Apple M1, 8 GiB RAM; project virtual environment uses Python 3.11.16. Approximately 22 GiB of disk space was available during discovery. These are feasibility observations rather than benchmark resource measurements.

`requirements-lock.txt` records the installed Python package versions used during the upgrade. The original dependency ranges remain in `requirements.txt`.

A read-only `google-genai` model-listing request succeeded. The configured `gemini-3.1-flash-lite` and both configured fallback model names were listed. This confirms availability in the account's model catalogue; it does not verify generation, quota, billing, stochastic reproducibility or scientific performance. No model generation was performed by this check.

Google's [Gemini 3.1 Flash-Lite announcement](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-1-flash-lite/) and [pricing documentation](https://ai.google.dev/gemini-api/docs/pricing) were checked on the same date. The standard text token prices for this model are USD 0.25 per million input tokens and USD 1.50 per million output tokens, including thinking tokens. These differ from the existing code's USD 0.05 / 0.20 estimates. A model catalogue listing does not establish the account's actual billing tier.

Credentials are excluded from Git. Their presence was checked without recording their values.
