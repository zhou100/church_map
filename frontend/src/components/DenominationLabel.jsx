import { denominationLabel } from '../churchProfile'

// Renders denominationLabel(); a website reading is marked so a visitor never
// takes it for the directory's or a verified tradition.
export default function DenominationLabel({ church, fallback = null }) {
  const label = denominationLabel(church)
  if (!label) return fallback
  return (
    <>
      {label.text}
      {label.fromWebsite && <span className="denom-source"> · from its website</span>}
    </>
  )
}
