import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { inject } from '@vercel/analytics'
import './index.css'
import './styles/focus.css'
import { Root } from './Root'

// Vercel Analytics — no-op outside Vercel (localhost, self-host) so it's
// safe to always call. Mirrors marketing/src/main.tsx.
inject()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
