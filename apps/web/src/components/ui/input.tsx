import * as React from "react"
import { Input as InputPrimitive } from "@base-ui/react/input"
import { cn } from "cn"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <InputPrimitive
      type={type}
      data-slot="input"
      className={cn(
        "h-10 max-sm:h-11 w-full min-w-0 rounded-[10px] border border-input bg-background px-3 text-[15px] transition-colors outline-none file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-panel disabled:text-muted-foreground read-only:bg-panel read-only:text-muted-foreground aria-invalid:border-primary",
        className
      )}
      {...props}
    />
  )
}

export { Input }
