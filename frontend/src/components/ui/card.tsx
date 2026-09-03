import * as React from "react"

import { cn } from "@/lib/utils"

function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-card text-card-foreground shadow-[var(--shadow-card)] transition-shadow duration-200",
        className
      )}
      {...props}
    />
  )
}

export { Card }
