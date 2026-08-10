# AtReady trust site

Local source for AtReady's multi-route product and trust layer. It is intentionally separate
from the plugin and runtime source surfaces and is not published or deployed from this directory.

Routes:

- `/atready/`
- `/support/`
- `/privacy/`
- `/terms/`
- `/security/`
- `/surfaces/`

The current copy is pre-submission working material. Public support, legal effective dates,
publisher identity, canonical URLs, and supported-surface claims must be finalized and verified
before publication.

## Local validation

```bash
npm run build
npm test
npm run lint
```
