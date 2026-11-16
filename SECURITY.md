# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Security Best Practices for Users

1. **API Keys & Tokens:** Never commit `config/settings.json` or `.env` files containing live OpenRouter API keys or GitHub Personal Access Tokens. Always use `config/settings.example.json` for version control.
2. **Local Network Exposure:** By default, the FastAPI server binds to `127.0.0.1` (localhost). Do not expose port `8000` to the public internet (`0.0.0.0`) without adding an authentication layer (e.g., OAuth2, Reverse Proxy with Basic Auth).
3. **Chat Data Privacy:** All conversations are stored locally in `data/assistant.db`. Ensure appropriate OS-level file permissions are set on the `data/` directory.

## Reporting a Vulnerability

If you discover a security vulnerability within this project, please do **not** open a public issue. Instead, report it privately via the repository's **Security Advisories** tab or contact the maintainers directly.
