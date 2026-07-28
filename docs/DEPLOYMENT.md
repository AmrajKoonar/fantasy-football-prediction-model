# Deployment

1. Generate validated JSON (`ffpm project generate` or the refresh workflow).
2. Ensure `metadata.json` has `dataMode: production` for a real site.
3. Deploy the `web` directory on Vercel (Hobby).
4. Set `NEXT_PUBLIC_SITE_URL`.
5. Do not run the ML pipeline inside the Vercel build.

See [USER_ACTIONS.md](USER_ACTIONS.md) for click-by-click steps.
