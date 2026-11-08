import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { Loader2Icon } from "lucide-react"
import { cn } from "cn"

// Gaya tombol mengikuti mockup FigCraft: radius 10, label 14 px Semi Bold, fokus = cincin tinta
// 2 px dengan jarak 2 px (token `--ring` = `--foreground`).
const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center gap-2 rounded-[10px] border border-transparent bg-clip-padding text-sm font-semibold whitespace-nowrap transition-colors outline-none select-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:bg-panel disabled:text-muted-foreground disabled:opacity-100 aria-invalid:border-primary [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary-hover",
        outline:
          "border-foreground bg-background text-foreground hover:bg-surface aria-expanded:bg-surface",
        secondary:
          "border-foreground bg-background text-foreground hover:bg-surface aria-expanded:bg-surface",
        ghost: "hover:bg-surface aria-expanded:bg-surface",
        destructive: "border-primary bg-background text-primary hover:bg-primary/10",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default:
          "h-9 max-sm:h-11 px-3.5 has-data-[icon=inline-end]:pr-2.5 has-data-[icon=inline-start]:pl-2.5",
        xs: "h-6 gap-1 rounded-[10px] px-2 text-xs in-data-[slot=button-group]:rounded-[10px] has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-8 gap-1 rounded-[10px] px-3 text-xs in-data-[slot=button-group]:rounded-[10px] has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-9 px-2.5 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        icon: "size-9 max-sm:size-11",
        "icon-xs":
          "size-6 rounded-[10px] in-data-[slot=button-group]:rounded-[10px] [&_svg:not([class*='size-'])]:size-3",
        "icon-sm":
          "size-8 rounded-[10px] in-data-[slot=button-group]:rounded-[10px]",
        "icon-lg": "size-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  loading = false,
  disabled,
  children,
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants> & { loading?: boolean }) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && <Loader2Icon className="size-3.5 animate-spin" aria-hidden />}
      {children}
    </ButtonPrimitive>
  )
}

export { Button, buttonVariants }
