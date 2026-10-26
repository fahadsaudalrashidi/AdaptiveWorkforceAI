import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { installAuthenticatedFetch } from './auth/authClient'

const root = document.getElementById('root')
if (!root) throw new Error('Root element not found')

installAuthenticatedFetch()

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
