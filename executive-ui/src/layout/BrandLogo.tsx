interface BrandLogoProps {
  className?: string
  variant?: 'standard' | 'white'
  mark?: boolean
  alt?: string
}

export function BrandLogo({ className = '', variant = 'standard', mark = false, alt = 'THRIVE Business Solutions' }: BrandLogoProps) {
  if (variant === 'white' || mark) {
    return (
      <img
        className={`brand-logo ${className}`}
        src={mark ? '/brand/thrive-mark.png' : '/brand/thrive-logo-white.png'}
        alt={alt}
      />
    )
  }
  return (
    <span className={`brand-logo-pair ${className}`} role="img" aria-label={alt}>
      <img className="brand-logo brand-logo-light" src="/brand/thrive-logo.png" alt="" aria-hidden="true" />
      <img className="brand-logo brand-logo-dark" src="/brand/thrive-logo-white.png" alt="" aria-hidden="true" />
    </span>
  )
}
