import Link from 'next/link'

const links = [
  ['Hiring', '/open-source-ats-alternative/'],
  ['Payroll', '/payroll-preparation/'],
  ['Indonesia', '/hr-automation-indonesia/'],
  ['Work with me', '/work-with-me/'],
] as const

export function SiteHeader() {
  return (
    <header className="site-header">
      <div className="container inner">
        <Link className="brand" href="/">
          HRAgents
        </Link>
        <nav className="nav" aria-label="Primary">
          {links.map(([label, href]) => (
            <Link key={href} href={href}>
              {label}
            </Link>
          ))}
          <a href="https://github.com/davinakmalyasha/HRAgents">GitHub</a>
        </nav>
      </div>
    </header>
  )
}
