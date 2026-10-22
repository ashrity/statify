import Link from "next/link";

const NAV = [
  { href: "/", label: "Weekly board" },
  { href: "/accuracy", label: "Accuracy" },
];

export function SiteHeader({ active }: { active: string }) {
  return (
    <header className="border-b border-border bg-surface/40">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <Link href="/" className="flex items-baseline gap-2">
          <span className="text-lg font-semibold tracking-tight">
            Stat<span className="text-accent">ify</span>
          </span>
          <span className="hidden text-xs text-muted sm:inline">
            projection minus the line
          </span>
        </Link>
        <nav className="flex gap-1 text-sm">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`rounded px-2 py-1 ${
                active === item.href
                  ? "bg-surface text-foreground"
                  : "text-muted hover:text-foreground"
              }`}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
