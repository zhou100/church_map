import { createContext, useContext, useState, useEffect } from 'react'
import { verifyGoogleCredential } from '../api/client'

const AuthContext = createContext(null)
export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)   // { user_id, name, email, avatar_url }
  const [token, setToken] = useState(null) // Google ID token

  // Restore session from localStorage
  useEffect(() => {
    const storedUser = localStorage.getItem('churchmap_user')
    const storedToken = localStorage.getItem('churchmap_token')
    if (storedUser && storedToken) {
      setUser(JSON.parse(storedUser))
      setToken(storedToken)
    }
  }, [])

  async function handleGoogleCredential(credential) {
    try {
      const userData = await verifyGoogleCredential(credential)
      setUser(userData)
      setToken(credential)
      localStorage.setItem('churchmap_user', JSON.stringify(userData))
      localStorage.setItem('churchmap_token', credential)
    } catch (e) {
      console.error('Sign-in error:', e)
    }
  }

  function logout() {
    setUser(null)
    setToken(null)
    localStorage.removeItem('churchmap_user')
    localStorage.removeItem('churchmap_token')
    window.google?.accounts.id.disableAutoSelect()
  }

  return (
    <AuthContext.Provider value={{ user, token, handleGoogleCredential, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
