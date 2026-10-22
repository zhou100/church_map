import { GOOGLE_CLIENT_ID, useAuth } from '../context/AuthContext'
import GoogleSignInButton from './GoogleSignInButton'

// Module-level so the button's effect doesn't re-render it on every parent render.
const HEADER_BUTTON = {
  type: 'standard',
  theme: 'outline',
  size: 'medium',
  text: 'signin',
  shape: 'pill',
  logo_alignment: 'left',
}

// Sign in (which also creates the account) or show who is signed in, for page
// headers. Rendered without an AuthProvider by scripts/prerender.mjs, so a
// missing context reads as signed out.
export default function AccountButton() {
  const { user, handleGoogleCredential, logout } = useAuth() ?? {}

  if (user) {
    return (
      <div className="account-button">
        {user.avatar_url && (
          <img src={user.avatar_url} alt="" className="reviewer-avatar" referrerPolicy="no-referrer" />
        )}
        <span className="account-name">{user.name?.split(' ')[0]}</span>
        <button type="button" className="signout-btn" onClick={logout}>Sign out</button>
      </div>
    )
  }

  if (!GOOGLE_CLIENT_ID) return null
  return (
    <div className="account-button">
      <GoogleSignInButton
        onCredential={handleGoogleCredential}
        options={HEADER_BUTTON}
        minHeight={32}
      />
    </div>
  )
}
