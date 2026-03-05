# Weaves

Weaves is a visual-first marketing website built with Next.js (App Router) and Tailwind CSS.
It includes responsive section layouts, theme support (light/dark), and a media-heavy homepage experience.

## Tech Stack

- Next.js 15 (App Router)
- React 19
- Tailwind CSS 4
- TypeScript
- `next-themes` for theme switching

## Local Development

Install dependencies:

```bash
npm install
```

Run the dev server:

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Available Scripts

- `npm run dev` - start local dev server
- `npm run build` - production build
- `npm run start` - run production server
- `npm run lint` - run ESLint

## Project Structure

- `src/app/page.tsx` - primary multi-section homepage
- `src/app/layout.tsx` - root layout and global providers
- `src/app/globals.css` - global styles and theme tokens
- `src/components/` - reusable UI components
- `public/images/` - static image assets used across sections

## Theme Notes

- Theme is managed with `next-themes`.
- Toggle is mounted globally in layout.
- For logos that require different assets per mode, use the `ThemedLogo` component at `src/components/themed-logo.tsx`.

## Deployment (Vercel + GoDaddy Domain)

Recommended setup: host on Vercel, keep DNS on GoDaddy.

1. Push this repo to GitHub/GitLab/Bitbucket.
2. Import the repo into [Vercel](https://vercel.com/new) and deploy.
3. In Vercel, go to `Project Settings -> Domains` and add:
   - `yourdomain.com`
   - `www.yourdomain.com`
4. In GoDaddy DNS, add/update:
   - `A` record: host `@` -> `76.76.21.21`
   - `CNAME` record: host `www` -> `cname.vercel-dns.com`
5. Wait for DNS propagation, then verify domain in Vercel.
6. SSL is issued automatically by Vercel once DNS is correct.

## Notes

- Keep all website media assets inside `public/images/` (not in `node_modules`).
- If DNS is managed elsewhere, follow equivalent A/CNAME records from Vercel domain setup.
