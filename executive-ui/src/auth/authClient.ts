export interface AuthUser {
  user_id: string
  username: string
  display_name: string
  email: string
  role: string
  must_change_password: boolean
}

const ACCESS_TOKEN_KEY = 'awi_access_token'
const REFRESH_TOKEN_KEY = 'awi_refresh_token'

export function getAccessToken() {
  return sessionStorage.getItem(ACCESS_TOKEN_KEY)
}

export function saveTokens(accessToken: string, refreshToken: string) {
  sessionStorage.setItem(ACCESS_TOKEN_KEY, accessToken)
  sessionStorage.setItem(REFRESH_TOKEN_KEY, refreshToken)
}

export function clearTokens() {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY)
  sessionStorage.removeItem(REFRESH_TOKEN_KEY)
}

export function installAuthenticatedFetch() {
  const originalFetch = window.fetch.bind(window)

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const requestUrl = input instanceof Request ? input.url : String(input)
    const path = new URL(requestUrl, window.location.origin).pathname
    const isApiRequest = path.startsWith('/api/')
    const isPublicAuthRequest = [
      '/api/auth/login',
      '/api/auth/refresh',
      '/api/auth/bootstrap',
    ].includes(path)
    const headers = new Headers(input instanceof Request ? input.headers : undefined)
    new Headers(init?.headers).forEach((value, key) => headers.set(key, value))

    if (isApiRequest && !isPublicAuthRequest) {
      const token = getAccessToken()
      if (token) headers.set('Authorization', `Bearer ${token}`)
    }

    const response = await originalFetch(input, { ...init, headers })
    if (response.status === 401 && path.startsWith('/api/local/')) {
      clearTokens()
      window.dispatchEvent(new Event('awi:session-expired'))
    }
    return response
  }
}

