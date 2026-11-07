import * as React from "react"
import { cn } from "cn"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex min-h-16 w-full rounded-[10px] border border-input bg-background px-3 py-2 text-[15px] transition-colors outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:bg-panel disabled:text-muted-foreground read-only:bg-panel read-only:text-muted-foreground aria-invalid:border-primary",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
