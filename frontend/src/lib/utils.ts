import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Shared text-input / select styling so every form field across the app
// (Import, Environments, dependency pickers, etc.) looks like one system.
export const inputClass = [
  "w-full rounded-lg border border-input bg-card",
  "px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground",
  "shadow-sm transition-all duration-150",
  "focus:outline-none focus:ring-2 focus:ring-ring/50 focus:border-primary",
  "disabled:opacity-50 disabled:cursor-not-allowed",
].join(" ")
