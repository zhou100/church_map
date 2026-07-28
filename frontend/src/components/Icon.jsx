const PATHS = {
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.3 2.5 3.5 5.5 3.5 9S14.3 18.5 12 21M12 3c-2.3 2.5-3.5 5.5-3.5 9s1.2 6.5 3.5 9" />
    </>
  ),
  phone: <path d="M7.1 3.5 9.6 8 7.8 9.8a14 14 0 0 0 6.4 6.4l1.8-1.8 4.5 2.5-.8 3.2c-.2.7-.8 1.2-1.6 1.2C9.6 20.7 3.3 14.4 2.7 5.9c0-.8.5-1.4 1.2-1.6l3.2-.8Z" />,
  pin: (
    <>
      <path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z" />
      <circle cx="12" cy="10" r="2.5" />
    </>
  ),
  arrow: (
    <>
      <path d="m5 12 14 0" />
      <path d="m14 7 5 5-5 5" />
    </>
  ),
  reviews: (
    <>
      <path d="M5 5h14v10H9l-4 4V5Z" />
      <path d="M8 9h8M8 12h5" />
    </>
  ),
  accessible: (
    <>
      <circle cx="12" cy="4.5" r="2" />
      <path d="M11 8v6l4 2 2 5M8 10h6M10.5 13.5A5 5 0 1 0 15 18" />
    </>
  ),
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m15.5 15.5 5 5" />
    </>
  ),
  check: <path d="m4 12 5 5L20 6" />,
}

export default function Icon({ name, size = 16, className = '' }) {
  return (
    <svg
      aria-hidden="true"
      className={`icon ${className}`.trim()}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  )
}
