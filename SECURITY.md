# Security Policy

## Supported versions

The current development line is the only actively maintained version.

## Security guidance

1. Never commit config/settings.json, .env files, API keys, or GitHub tokens.
2. Stored provider secrets are currently kept as plaintext in the local ignored JSON file. Protect the Windows user account and filesystem.
3. GET /api/settings redacts secret values, but this does not replace local filesystem protection.
4. The application does not implement user authentication. Run it on localhost only; do not bind it to 0.0.0.0 or expose port 8000 to an untrusted network.
5. Chat history is stored locally in data/chat_history.db. Back it up and restrict access as appropriate.

## Reporting a vulnerability

Please do not publish exploitable details in a public issue. Use GitHub's private vulnerability reporting / Security Advisories feature.
