import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold leading-normal transition-colors [&_svg]:size-3 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        success: "bg-success-bg text-success border-success-border",
        danger: "bg-danger-bg text-danger border-danger-border",
        warning: "bg-warning-bg text-warning border-warning-border",
        info: "bg-info-bg text-info border-info-border",
        neutral: "bg-neutral-bg text-neutral border-neutral-border",
        violet: "bg-accent text-accent-foreground border-primary/25",
      },
    },
    defaultVariants: {
      variant: "neutral",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {
  icon?: React.ReactNode
}

function Badge({ className, variant, icon, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant, className }))} {...props}>
      {icon}
      {children}
    </span>
  )
}

export { Badge, badgeVariants }
