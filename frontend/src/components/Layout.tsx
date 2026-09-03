import { NavLink, Outlet } from "react-router-dom";
import { Sparkles } from "lucide-react";

function navClass({ isActive }: { isActive: boolean }) {
  return [
    "relative text-sm font-medium px-3 py-1.5 rounded-lg transition-all duration-150",
    isActive
      ? "text-primary-foreground bg-primary shadow-sm shadow-primary/25"
      : "text-muted-foreground hover:text-foreground hover:bg-accent/70",
  ].join(" ");
}

export function Layout() {
  return (
    <div className="min-h-screen flex flex-col">
      {/* Top nav bar */}
      <header className="sticky top-0 z-30 border-b border-border/80 bg-background/80 backdrop-blur-md supports-backdrop-blur:bg-background/60">
        <div className="max-w-5xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg ai-gradient text-white shadow-md shadow-primary/30">
              <Sparkles className="h-4 w-4" strokeWidth={2.5} />
            </span>
            <span className="font-extrabold tracking-tight text-foreground text-[1.05rem]">
              API <span className="brand-gradient-text">Pilot</span>
            </span>
          </div>
          <nav className="flex items-center gap-1">
            <NavLink to="/" end className={navClass}>
              Suites
            </NavLink>
            <NavLink to="/import" className={navClass}>
              Import
            </NavLink>
            <NavLink to="/environments" className={navClass}>
              Environments
            </NavLink>
            <NavLink to="/history" className={navClass}>
              History
            </NavLink>
          </nav>
        </div>
      </header>

      {/* Page content */}
      <main className="flex-1">
        <div className="max-w-5xl mx-auto px-4 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
